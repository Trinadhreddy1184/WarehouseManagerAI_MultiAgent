import logging
from typing import List, Tuple
import boto3
import json
from src.agents.base import AgentBase
from src.database.db_manager import get_db
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)


def _format_schema_for_prompt(tables: dict[str, list[str]]) -> str:
    """Return a trimmed, human-readable schema summary for prompting."""

    if not tables:
        return ""

    schema_lines = []
    for table, cols in tables.items():
        display_cols = cols[:30]
        cols_list = ", ".join(display_cols)
        line = f"{table} ({cols_list})"
        if len(cols) > len(display_cols):
            line += f", ... ({len(cols) - len(display_cols)} more columns)"
        schema_lines.append(line)

    max_chars = 4000
    trimmed_lines = []
    running_total = 0
    for line in schema_lines:
        line_len = len(line) + 1  # account for newline
        if running_total + line_len > max_chars:
            trimmed_lines.append("... (schema truncated for brevity)")
            break
        trimmed_lines.append(line)
        running_total += line_len

    return "\n".join(trimmed_lines)

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
        # Set up Bedrock client, reuse if available
        try:
            self.bedrock_client = self.llm_manager.llm._br  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("Bedrock client not found on LLMManager; creating a new one: %s", e)
            region = (
                self.llm_manager.config.get("bedrock", {}).get("region_name")
                if hasattr(self.llm_manager, "config")
                else None
            ) or "us-east-1"
            self.bedrock_client = boto3.client("bedrock-runtime", region_name=region)

    def name(self) -> str:
        return self.NAME

    def score_request(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
    ) -> float:
        text = (user_request or "").lower().strip()
        if not text:
            return 0.0

        aggregate_triggers = [
            " most ",
            " least ",
            " highest ",
            " lowest ",
            " average ",
            " averages ",
            " sum ",
            " total ",
            " number of ",
            " count ",
            "distinct",
            " per store",
            " by store",
            " top ",
            " bottom ",
        ]

        if any(phrase in text for phrase in aggregate_triggers):
            return 0.95

        analytic_keywords = [
            "inventory",
            "warehouse",
            "stock",
            "store",
            "availability",
            "available",
            "list",
            "show",
            "lookup",
            "report",
            "catalog",
            "sku",
            "product",
            "brand",
            "units",
            "quantity",
            "do we have",
            "in stock",
            "app_inventory",
        ]

        follow_up = False
        if len(chat_history) >= 2:
            prev_role, prev_message = chat_history[-2]
            if prev_role == "assistant":
                prev_text = prev_message.lower()
                if any(keyword in prev_text for keyword in ("result", "inventory", "product", "store")):
                    follow_up = True

        if any(keyword in text for keyword in analytic_keywords) or follow_up:
            return 0.8

        return 0.0

    def handle(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
    ) -> str:
        if not chat_history:
            raise ValueError("chat_history must include the current user request")

        logger.info("SqlQueryAgent handling: %s", user_request)

        context_messages: List[Tuple[str, str]] = chat_history[:-1]
        conversation_context = ""
        if context_messages:
            recent = context_messages[-6:]
            formatted = []
            for role, message in recent:
                snippet = message.strip()
                if not snippet:
                    continue
                formatted.append(f"{role.upper()}: {snippet}")
            if formatted:
                conversation_context = "\n".join(formatted)

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
            schema_str = _format_schema_for_prompt(tables)
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
                schema_str = _format_schema_for_prompt(tables)
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

        if conversation_context:
            system_prompt += "Recent conversation:\n" + conversation_context + "\n"

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

