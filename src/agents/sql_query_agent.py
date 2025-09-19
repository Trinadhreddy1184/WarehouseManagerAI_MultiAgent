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
            configured_region = (
                self.llm_manager.config.get("bedrock", {}).get("region_name")
                if hasattr(self.llm_manager, "config")
                else None
            )
            default_region = "us-east-1"
            if configured_region and configured_region != default_region:
                logger.warning(
                    "SqlQueryAgent overriding region %s with required region %s",
                    configured_region,
                    default_region,
                )
            self.bedrock_client = boto3.client(
                "bedrock-runtime", region_name=default_region
            )

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

        analytic_keywords = [
            "inventory",
            "inventory level",
            "warehouse",
            "stock",
            "stocked",
            "store",
            "availability",
            "available",
            "list",
            "show",
            "lookup",
            "report",
            "catalog",
            "catalogue",
            "sku",
            "skus",
            "item",
            "items",
            "product",
            "brand",
            "units",
            "cases",
            "quantity",
            "supply",
            "do we have",
            "in stock",
            "carrying",
            "carry",
            "app_inventory",
        ]

        question_leads = [
            "how many",
            "how much",
            "what is",
            "what are",
            "which",
            "where",
            "show me",
            "list",
            "give me",
            "provide",
            "find",
            "are there",
            "do we have",
        ]

        follow_up = False
        if len(chat_history) >= 2:
            prev_role, prev_message = chat_history[-2]
            if prev_role == "assistant":
                prev_text = prev_message.lower()
                if any(keyword in prev_text for keyword in ("result", "inventory", "product", "store")):
                    follow_up = True
        score = 0.0

        if any(phrase in text for phrase in aggregate_triggers):
            score = max(score, 0.95)

        domain_hit = any(keyword in text for keyword in analytic_keywords)
        if domain_hit:
            score = max(score, 0.8)

        question_hit = text.endswith("?") or any(
            text.startswith(lead) or f" {lead}" in text for lead in question_leads
        )
        if question_hit and domain_hit:
            score = max(score, 0.85)
        elif question_hit:
            score = max(score, 0.65)

        if follow_up:
            score = max(score, 0.8)

        return score

    def handle(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
        **_: object,
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
        system_prompt = (
            "You are a SQL expert for a warehouse inventory database.\n"
            "Carefully analyse the user's question and determine which tables and columns are required before writing SQL.\n"
        )
        if schema_str:
            system_prompt += "The database has the following tables and columns:\n"
            system_prompt += schema_str + "\n"
        system_prompt += (
            "Follow these rules when writing the query:\n"
            "1. Use only read-only SELECT statements; never modify data.\n"
            "2. Prefer `app_inventory` for stock levels and join `vip_products` or related tables when names are required.\n"
            "3. When matching user-supplied names or identifiers, use case-insensitive comparisons such as ILIKE with surrounding percent wildcards to handle partial matches.\n"
            "4. Apply aggregates (COUNT, SUM, AVG, etc.) when the question implies totals or averages.\n"
            "5. For list-style outputs, include `LIMIT 50` to keep results concise unless the question specifies a different limit.\n"
            "6. Do not invent filters that the user did not mention.\n"
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
        display_sql = sql_clean if sql_clean.endswith(";") else f"{sql_clean};"
        if not sql_clean.lower().startswith("select"):
            logger.warning("Generated query is not a SELECT statement: %s", sql_clean)
            return (
                "I can only execute read-only SELECT queries. The model "
                "suggested: "
                f"{display_sql}"
            )

        # Execute the query
        try:
            df = self.db.query_df(sql_clean, None)
        except Exception as e:
            logger.exception("SQL execution failed: %s\nSQL was: %s", e, sql_clean)
            err = str(e).lower()
            if "does not exist" in err:
                # Likely missing table or column
                return (
                    "SQL Query:\n"
                    f"{display_sql}\n\n"
                    "I couldn't execute the query: one of the tables or columns was not found."
                )
            return (
                "SQL Query:\n"
                f"{display_sql}\n\n"
                "I couldn't execute the query due to an error."
            )

        # Check if result is empty
        if df.empty:
            return "SQL Query:\n" + display_sql + "\n\nNo results found."

        # Format results
        # Single value aggregate (1x1)
        if df.shape == (1, 1):
            col = df.columns[0]
            val = df.iloc[0, 0]
            return (
                "SQL Query:\n"
                f"{display_sql}\n\n"
                f"Result:\n{col}: **{val}**"
            )

        # Single row with multiple columns -> inline key: value
        if df.shape[0] == 1:
            pairs = [f"{c}: {df.iloc[0][c]}" for c in df.columns]
            return (
                "SQL Query:\n"
                f"{display_sql}\n\n"
                "Result:\n" + " | ".join(pairs)
            )

        # Multi-row results -> Markdown table (code block with pipes)
        header = " | ".join(str(c) for c in df.columns)
        lines = [" | ".join(str(x) for x in row) for _, row in df.iterrows()]
        # Limit number of rows in output for brevity
        lines_display = lines[:20]
        table_block = "\n".join([header] + lines_display)
        if len(lines) > 20:
            table_block += f"\n... ({len(lines) - 20} more rows)"
        return (
            "SQL Query:\n"
            f"{display_sql}\n\n"
            "Results:\n```\n"
            + table_block
            + "\n```"
        )

