import logging
from typing import List, Tuple

import boto3
from src.agents.base import AgentBase
from src.database.db_manager import get_db
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)


class SqlQueryAgent(AgentBase):
    """
    Use the Bedrock LLM to generate a SQL SELECT and execute it safely
    against the warehouse database (preferring the `app_inventory` view).

    - Only SELECT statements are allowed.
    - If the result is empty, return "No results found."
    - Formats single-value aggregates nicely; multi-row results are listed.
    """

    NAME = "sql_query"

    def __init__(self, llm_manager: LLMManager) -> None:
        self.llm_manager = llm_manager
        self.db = get_db()
        # Reuse Bedrock client from the LLM if available; otherwise build our own
        try:
            self.bedrock_client = self.llm_manager.llm._br  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("Bedrock client not found on LLM; creating a new one: %s", e)
            region = (
                self.llm_manager.config.get("bedrock", {}).get("region_name")
                if hasattr(self.llm_manager, "config")
                else None
            ) or "us-east-1"
            self.bedrock_client = boto3.client("bedrock-runtime", region_name=region)

    def name(self) -> str:
        return self.NAME

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        """
        Return a moderate-high score if the question smells like an
        analytical/SQL-style question so this agent is tried early.
        """
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

        system_prompt = (
            "You are a SQL expert for a retail inventory database.\n"
            "Output ONLY a single SQL SELECT statement (no backticks, no prose).\n"
            "Prefer the unified view `app_inventory` with columns like:\n"
            "  store (text), product_name (text), brand_name (text)\n"
            "You may also use base tables if necessary (e.g., vip_products, vip_brands).\n"
            "Do not modify data. Do not include comments or explanations."
        )
        messages = [
            {"role": "system", "content": [{"text": system_prompt}]},
            {"role": "user", "content": [{"text": user_request}]},
        ]

        # Call Bedrock Nova to draft the SQL (catching permission issues gracefully)
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
            return ("I couldn't formulate a query for that yet. "
                    "Model permissions may be missing; please verify Bedrock access.")

        # Safety: allow only SELECTs
        sql_clean = sql.rstrip(";").strip()
        if not sql_clean.lower().startswith("select"):
            logger.warning("Generated non-SELECT query; refusing to run: %s", sql_clean)
            return "I can only run read-only SELECT queries."

        # Execute
        try:
            df = self.db.query_df(sql_clean, None)
        except Exception as e:
            logger.exception("SQL execution failed: %s\nSQL was: %s", e, sql_clean)
            return "I couldn't execute the query."

        if df.empty:
            return "No results found."

        # Formatting
        if df.shape == (1, 1):
            # Single cell (likely aggregate)
            col = df.columns[0]
            val = df.iloc[0, 0]
            return f"{col}: **{val}**"

        if df.shape[0] == 1:
            # One row, multiple columns → inline key: value pairs
            pairs = [f"{c}: {df.iloc[0][c]}" for c in df.columns]
            return " | ".join(pairs)

        # Multi-row display with header
        header = " | ".join(str(c) for c in df.columns)
        lines = [" | ".join(str(x) for x in row) for _, row in df.iterrows()]
        block = "\n".join([header] + lines[:20])  # cap output
        if len(lines) > 20:
            block += f"\n... ({len(lines) - 20} more rows)"
        return "**Results:**\n```\n" + block + "\n```"

