import logging
from typing import List, Tuple
from .base import AgentBase
from src.llm.manager import LLMManager
from src.database.db_manager import get_db

# from sqlalchemy import event

logger = logging.getLogger(__name__)

try:
    from pgvector.psycopg2 import register_vector
except ImportError:
    register_vector = None
    logger.info("pgvector module not available; continuing with DuckDB-only mode.")

class VectorSearchAgent(AgentBase):
    """
    Agent performing semantic similarity search on product embeddings stored in the database.
    """
    NAME = "vector_search"

    def __init__(self, llm_manager: LLMManager) -> None:
        self.llm_manager = llm_manager
        # Initialize DB connection; pgvector registration is skipped while using DuckDB only
        self.db = get_db()
        self._enabled = self.llm_manager.is_enabled()
        if not self._enabled:
            logger.info(
                "VectorSearchAgent initialised with LLM disabled; queries will return a placeholder"
            )
        # try:
        #     engine = self.db.engine
        # except AttributeError:
        #     engine = getattr(self.db, "_db").engine
        # if register_vector is not None:
        #     event.listen(engine, "connect", lambda conn, rec: register_vector(conn))
        #     logger.debug("VectorSearchAgent initialized with pgvector adapter registered.")
        logger.info("VectorSearchAgent running with DuckDB backend; pgvector registration disabled.")

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        """
        Return a relevance score for this agent.  Lower priority if the query
        contains product/brand keywords (to let the ProductLookupAgent handle them).
        Otherwise return a baseline score.
        """
        if not self._enabled:
            return 0.0
        text = (user_request or "").lower()
        from .product_lookup_agent import ProductLookupAgent
        if any(keyword in text for keyword in ProductLookupAgent._KEYWORDS):
            # De-prioritize queries that look like simple product lookups
            return 0.0
        # Baseline score for general semantic queries (catch-all, like GeneralChatAgent)
        return 0.5  # same baseline used by GeneralChatAgent

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        """
        Compute the query embedding and perform a pgvector similarity search in vip_products.
        """
        if not self._enabled:
            return (
                "Vector search is disabled while the language model is offline. "
                "Enable the LLM to restore semantic lookups."
            )
        text = (user_request or "").strip()
        if not text:
            return "What product or feature are you interested in?"

        # Compute embedding via the Bedrock embedding model
        try:
            embeddings = self.llm_manager.get_embedding()
            query_vector = embeddings.embed_query(text)
        except Exception as e:
            logger.exception("Failed to compute embedding: %s", e)
            return "No vector results found."

        # Perform vector similarity search in the database (with DuckDB fallback support)
        try:
            df = self.db.vector_similarity(query_vector, limit=5)
        except Exception as e:
            logger.exception("Vector search query failed: %s", e)
            return "No vector results found."

        # If no rows found, fallback
        if df.empty:
            logger.info("No vector search results for query: %s", text)
            return "No vector results found."

        # Format results into a user-friendly response
        products = []
        for _, row in df.iterrows():
            name = row.get("product_name") or "Unknown product"
            brand = row.get("brand_name")
            if brand:
                products.append(f"{name} by {brand}")
            else:
                products.append(name)

        if not products:
            return "No vector results found."
        if len(products) == 1:
            return f"I found this product: {products[0]}"
        # List multiple candidates
        return "Here are some products you might be interested in:\n" + "\n".join(f"- {p}" for p in products)

