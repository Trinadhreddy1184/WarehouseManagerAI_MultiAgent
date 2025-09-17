import logging
from typing import List, Dict, Tuple
import json

try:
    import boto3
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore[assignment]
from src.agents.base import AgentBase
from src.database.db_manager import get_db
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)

class SqlQueryAgent(AgentBase):
    """
    Use the Bedrock LLM to generate a SQL SELECT and execute it safely
    against the warehouse database.

    - Only SELECT statements are allowed.
    - If the result is empty, return "No results found."
    - Formats single-value aggregates nicely; multi-row results are listed as Markdown table.
    """
    NAME = "sql_query"

    def __init__(self, llm_manager: LLMManager) -> None:
        self.llm_manager = llm_manager
        self.db = get_db()
        self._enabled = self.llm_manager.is_enabled()
        self.bedrock_client = None
        if self._enabled:
            try:
                self.bedrock_client = self.llm_manager.llm._br  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning("Bedrock client not found on LLMManager; creating a new one: %s", e)
                region = (
                    self.llm_manager.config.get("bedrock", {}).get("region_name")
                    if hasattr(self.llm_manager, "config")
                    else None
                ) or "us-east-1"
                if boto3 is None:
                    logger.error("boto3 is unavailable; SQL generation cannot run")
                    self._enabled = False
                else:
                    self.bedrock_client = boto3.client(
                        "bedrock-runtime", region_name=region
                    )
        if not self._enabled:
            logger.info("SqlQueryAgent initialised with LLM disabled")

    def name(self) -> str:
        return self.NAME

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        text = (user_request or "").lower()
        triggers = [
            " most ", " least ", " highest ", " lowest ",
            " average ", " averages ", " sum ", " total ",
            " number of ", " count ", "distinct", " per store", " by store",
        ]
        if any(t in text for t in triggers):
            return 0.8
        return 0.0

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        logger.info("SqlQueryAgent handling: %s", user_request)

        if not self._enabled or self.bedrock_client is None:
            return (
                "Automated SQL generation is disabled while the language model is offline. "
                "Enable the LLM to restore this feature."
            )

        # Load database schema from JSON if available, otherwise introspect
        schema_str = ""
        try:
            with open("src/database/schema.json", "r") as f:
                schema_json = json.load(f)
            tables = {}
            # Determine format of schema JSON
            if isinstance(schema_json, dict):
                if "tables" in schema_json and isinstance(schema_json["tables"], dict):
                    tables = schema_json["tables"]
                else:
                    for table, cols in schema_json.items():
                        if isinstance(cols, list):
                            tables.setdefault(table, []).extend(cols)
                        elif isinstance(cols, dict) and "columns" in cols:
                            tables.setdefault(table, []).extend(cols["columns"])
            elif isinstance(schema_json, list):
                for entry in schema_json:
                    if isinstance(entry, dict):
                        table = entry.get("table") or entry.get("name")
                        columns = entry.get("columns") or entry.get("fields") or []
                        if table and isinstance(columns, list):
                            tables.setdefault(table, []).extend(columns)
            # Build schema lines
            schema_lines = []
            for table, cols in tables.items():
                cols_list = ", ".join(cols)
                schema_lines.append(f"{table} ({cols_list})")
            schema_str = "\n".join(schema_lines)
        except Exception as e:
            logger.exception("Failed to load schema.json: %s", e)
            # Fallback: introspect the database schema
            try:
                schema_query = """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position;
                """
                schema_df = self.db.query_df(schema_query, None)
                tables = {}
                for table, col in zip(schema_df["table_name"], schema_df["column_name"]):
                    tables.setdefault(table, []).append(col)
                schema_lines = []
                for table, cols in tables.items():
                    cols_list = ", ".join(cols)
                    schema_lines.append(f"{table} ({cols_list})")
                schema_str = "\n".join(schema_lines)
            except Exception as e2:
                logger.exception("Failed to retrieve database schema: %s", e2)
                schema_str = ""

        # Build system prompt including schema information
        system_prompt = "You are a SQL expert for a warehouse inventory database.\n"
        if schema_str:
            system_prompt += "The database has the following tables and columns:\n"
            system_prompt += schema_str + "\n"
        system_prompt += (
            "Output ONLY a single SQL SELECT statement (no backticks, no explanations). "
            "Do not modify or write any data."
        )

        messages = [
            {"role": "system", "content": [{"text": system_prompt}]},
            {"role": "user", "content": [{"text": user_request}]},
        ]

        # Call Bedrock LLM to generate the SQL (Nova model)
        try:
            resp = self.bedrock_client.converse(
                modelId="amazon.nova-pro-v1:0",
                messages=messages,
                inferenceConfig={
                    "maxTokens": 256,
                    "temperature": 0.0,
                    "topP": 0.9,
                },
            )
            sql = resp["output"]["message"]["content"][0]["text"].strip()
        except Exception as e:
            logger.exception("Bedrock converse failed: %s", e)
            return ("I couldn't formulate a query for that request. "
                    "Please check your AWS Bedrock permissions or try again later.")

        # Ensure only SELECT queries are allowed
        sql_clean = sql.rstrip(";").strip()
        if not sql_clean.lower().startswith("select"):
            logger.warning("Generated query is not a SELECT statement: %s", sql_clean)
            return "I can only execute read-only SELECT queries."

        # Execute the query
        try:
            df = self.db.query_df(sql_clean, None)
        except Exception as e:
            logger.exception("SQL execution failed: %s\nSQL was: %s", e, sql_clean)
            err = str(e).lower()
            if "does not exist" in err:
                # Likely missing table or column
                return "I couldn't execute the query: one of the tables or columns was not found."
            return "I couldn't execute the query due to an error."

        # Check if result is empty
        if df.empty:
            return "No results found."

        # Format results
        # Single value aggregate (1x1)
        if df.shape == (1, 1):
            col = df.columns[0]
            val = df.iloc[0, 0]
            return f"{col}: **{val}**"

        # Single row with multiple columns -> inline key: value
        if df.shape[0] == 1:
            pairs = [f"{c}: {df.iloc[0][c]}" for c in df.columns]
            return " | ".join(pairs)

        # Multi-row results -> Markdown table (code block with pipes)
        header = " | ".join(str(c) for c in df.columns)
        lines = [" | ".join(str(x) for x in row) for _, row in df.iterrows()]
        # Limit number of rows in output for brevity
        lines_display = lines[:20]
        table_block = "\n".join([header] + lines_display)
        if len(lines) > 20:
            table_block += f"\n... ({len(lines) - 20} more rows)"
        return "**Results:**\n```\n" + table_block + "\n```"

