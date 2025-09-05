"""Agent specialising in simple product lookups.

Given a user request, this agent attempts to parse out product or brand names
and searches the imported ``vip_products`` and ``vip_brands`` tables for
matches. If there are no obvious product terms in the prompt the agent assigns
itself a low score so that other agents can take over.
"""
from __future__ import annotations

import logging
import re
from typing import List, Tuple

from .base import AgentBase
from sqlalchemy.exc import ProgrammingError
from src.database.db_manager import get_db


logger = logging.getLogger(__name__)


class ProductLookupAgent(AgentBase):
    """Return product information from the database if the query mentions inventory."""

    # Keywords that suggest the user is asking about product availability
    KEYWORDS = [
        "product", "brand", "stock", "inventory", "availability", "price"
    ]

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        # Very naive scoring: count keyword occurrences
        lower = user_request.lower()
        hits = sum(1 for kw in self.KEYWORDS if kw in lower)

        score = min(1.0, hits / len(self.KEYWORDS)) if hits else 0.0
        logger.debug("ProductLookupAgent score=%s for request=%s", score, user_request)
        # Normalize to [0,1]; at least 0.0 if no hits
        return score

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        # Extract potential query terms by taking words longer than 3 letters
        tokens = re.findall(r"\b\w{4,}\b", user_request.lower())
        q = " ".join(tokens)
        if q:
            sql = """
                SELECT p.product_name, b.brand_name
                FROM vip_products p
                LEFT JOIN vip_brands b ON p.vip_brand_id = b.vip_brand_id
                WHERE p.product_name ILIKE :pattern
                   OR b.brand_name   ILIKE :pattern
                LIMIT 5
            """
            params = {"pattern": f"%{q}%"}
        else:
            sql = """
                SELECT p.product_name, b.brand_name
                FROM vip_products p
                LEFT JOIN vip_brands b ON p.vip_brand_id = b.vip_brand_id
                LIMIT 5
            """
            params = None
        logger.debug("Executing SQL: %s", sql)
        try:
            df = get_db().query_df(sql, params)
        except ProgrammingError:
            logger.exception("Required tables are missing")
            return "Inventory data is unavailable."
        if df.empty:
            logger.info("No products found for query: %s", q)
            return "I'm sorry, I couldn't find any matching products."
        rows = [
            f"{row.product_name} by {row.brand_name or 'Unknown brand'}"
            for _, row in df.iterrows()
        ]
        result = "Here are some products I found:\n" + "\n".join(rows)
        logger.debug("Lookup result: %s", result)
        return result
