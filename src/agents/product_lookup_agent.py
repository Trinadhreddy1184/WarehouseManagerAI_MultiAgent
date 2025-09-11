import logging
import re
from typing import Optional, List, Dict, Tuple

from sqlalchemy.exc import ProgrammingError

from .base import AgentBase
from src.database.db_manager import get_db

logger = logging.getLogger(__name__)

class ProductLookupAgent(AgentBase):
    """
    Looks up products/brands from the relational inventory using the unified view `app_inventory`.
    - Supports simple keyword search on product_name / brand_name.
    - Supports optional `store <id|name>` filter, e.g. "gin in store 2".
    - Supports count queries, e.g. "how many products in store 1?" or "count gin items".
    Returns either a short list (up to 5 rows) or a single sentence with the total.
    """
    NAME = "product_lookup"

    # Keywords that suggest this agent is relevant
    _KEYWORDS: List[str] = [
        "product",
        "brand",
        "sku",
        "item",
        "stock",
        "inventory",
        "have",
        "store",   # important for store-scoped queries
        "price",
        "available",
        "availability",
    ]

    # Very light stopword list for extracting a fuzzy pattern from free text
    _STOPWORDS = {
        "how", "many", "much", "count", "items", "products", "inventory", "stock",
        "do", "we", "you", "they", "is", "are", "in", "at", "on", "of", "for",
        "to", "and", "or", "the", "a", "an", "any", "show", "list", "find",
        "brand", "brands", "product", "sku", "skus", "available", "availability",
        "store", "stores", "have", "has", "with", "by", "from", "please",
    }

    def name(self) -> str:
        return self.NAME

    # --- Agent routing signal -------------------------------------------------

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        """
        Heuristic score: proportional to number of inventory-related keywords present.
        """
        text = user_request.lower()
        score = sum(1 for kw in self._KEYWORDS if kw in text)
        # normalize to [0,1] (cap after 5 matches)
        return min(score / 5.0, 1.0)

    # --- Core handler ---------------------------------------------------------

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        """
        Execute a lookup against the `app_inventory` view.

        app_inventory expected columns used here:
          - store (TEXT, may be NULL)
          - product_name (TEXT)
          - brand_name (TEXT)
        """
        user_request = (user_request or "").strip()
        if not user_request:
            return "Please tell me what product or brand to look up."

        # Extract store filter like "store 2" / "store abc"
        store_match = re.search(r"\bstore\s+([A-Za-z0-9_\-]+)\b", user_request, flags=re.IGNORECASE)
        store_filter = store_match.group(1) if store_match else None

        # Detect a count query
        count_query = bool(
            re.search(r"\bhow\s+many\b", user_request, flags=re.IGNORECASE)
            or re.search(r"\bcount\b", user_request, flags=re.IGNORECASE)
        )

        # Build a fuzzy search pattern from remaining content
        q = self._extract_query_pattern(user_request, store_filter)

        # Build SQL
        if q or store_filter:
            sql = "SELECT COUNT(*) AS total FROM app_inventory" if count_query \
                  else "SELECT store, product_name, brand_name FROM app_inventory"

            conditions = []
            params = {}

            if q:
                conditions.append("(product_name ILIKE :pattern OR brand_name ILIKE :pattern)")
                params["pattern"] = f"%{q}%"

            if store_filter:
                conditions.append("store ILIKE :store_pattern")
                params["store_pattern"] = f"%{store_filter}%"

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            if not count_query:
                sql += " LIMIT 5"

            logger.debug("ProductLookupAgent SQL: %s | params=%s", sql, params)

            try:
                df = get_db().query_df(sql, params)
            except ProgrammingError:
                logger.exception("Required tables/view are missing (expected `app_inventory`).")
                return "Inventory data is unavailable."

            if df.empty:
                logger.info("No results for query pattern=%r store=%r", q, store_filter)
                return "No products found."

            if count_query:
                total = int(df.iloc[0]["total"])
                if store_filter and q:
                    return f'Store {store_filter} has {total} items matching "{q}".'
                elif store_filter:
                    return f"Store {store_filter} has {total} items."
                elif q:
                    return f'There are {total} items matching "{q}".'
                else:
                    return f"There are {total} items in the inventory."
            else:
                rows = [
                    f"{(row.get('store') or 'Unknown store')}: "
                    f"{row.get('product_name') or 'Unknown product'} by "
                    f"{row.get('brand_name') or 'Unknown brand'}"
                    for _, row in df.iterrows()
                ]
                return "Here are some products I found:\n" + "\n".join(rows)

        # No query terms at all: show a small sample to guide the user
        try:
            df = get_db().query_df(
                "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5", None
            )
        except ProgrammingError:
            logger.exception("Required tables/view are missing (expected `app_inventory`).")
            return "Inventory data is unavailable."

        if df.empty:
            return "No products found."

        rows = [
            f"{(row.get('store') or 'Unknown store')}: "
            f"{row.get('product_name') or 'Unknown product'} by "
            f"{row.get('brand_name') or 'Unknown brand'}"
            for _, row in df.iterrows()
        ]
        return "Here are some products I found:\n" + "\n".join(rows)

    # --- Helpers --------------------------------------------------------------

    def _extract_query_pattern(self, text: str, store_filter: Optional[str]) -> Optional[str]:
        """
        Extract a lightweight fuzzy pattern from the user request,
        excluding obvious stopwords and 'store <x>' mention.
        """
        # remove 'store X' segment from text to avoid polluting pattern
        if store_filter:
            text = re.sub(rf"\bstore\s+{re.escape(store_filter)}\b", " ", text, flags=re.IGNORECASE)

        # tokenization (very light)
        tokens = re.findall(r"[A-Za-z0-9_\-]+", text.lower())

        keywords = [t for t in tokens if t not in self._STOPWORDS and len(t) > 2]
        if not keywords:
            return None

        # Join first few keywords into a single fuzzy pattern
        # (This is intentionally simple; the DB uses ILIKE on product_name/brand_name)
        pattern = " ".join(keywords[:5])
        return pattern or None

