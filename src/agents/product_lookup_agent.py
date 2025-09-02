"""Agent specialising in simple product lookups.

Given a user request, this agent attempts to parse out product or brand names
and performs a fuzzy search against an ``app_inventory`` table in the
database.  If there are no obvious product terms in the prompt the agent
assigns itself a low score so that other agents can take over.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .base import AgentBase
from ..database.db_manager import get_db


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
        # Normalize to [0,1]; at least 0.0 if no hits
        return min(1.0, hits / len(self.KEYWORDS)) if hits else 0.0

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        # Extract potential query terms by taking words longer than 3 letters
        tokens = re.findall(r"\b\w{4,}\b", user_request.lower())
        q = " ".join(tokens)
        q_esc = q.replace("'", "''")
        if q_esc:
            sql = f"""
                SELECT store, product_name, brand_name
                FROM app_inventory
                WHERE product_name ILIKE '%{q_esc}%'
                   OR brand_name   ILIKE '%{q_esc}%'
                LIMIT 5
            """
        else:
            sql = "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5"
        df = get_db().query_df(sql)
        if df.empty:
            return "I'm sorry, I couldn't find any matching products."
        # Format the DataFrame into a human readable list
        rows = [f"{row.store}: {row.product_name} by {row.brand_name}" for _, row in df.iterrows()]
        return "Here are some products I found:\n" + "\n".join(rows)
