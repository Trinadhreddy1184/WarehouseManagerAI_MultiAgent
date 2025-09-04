"""Agent that performs semantic product search using pgvector."""
from __future__ import annotations

import logging
from typing import List, Tuple

from sqlalchemy import text
try:  # Optional dependency for pgvector
    from pgvector.sqlalchemy import register_vector  # type: ignore
except Exception:  # pragma: no cover - import fallback
    register_vector = None  # type: ignore

from .base import AgentBase
from src.database.db_manager import get_db
from src.llm.embeddings import EmbeddingManager
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)


class VectorSearchAgent(AgentBase):
    """Retrieve similar products via embeddings and answer with context."""

    def __init__(self, llm_manager: LLMManager, top_k: int = 5) -> None:
        self.llm_manager = llm_manager
        self.embedder = EmbeddingManager()
        self.db = get_db()
        if register_vector:
            register_vector(self.db.engine)
        else:  # pragma: no cover - dependency missing
            logger.warning("pgvector package not installed; VectorSearchAgent disabled")
        self.top_k = top_k

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        # Provide a moderate score so this agent is tried before the general chat agent
        return 0.6

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        logger.info("VectorSearchAgent handling request")
        embedding = self.embedder.embed_query(user_request)
        sql = text(
            """
            SELECT store, product_name, brand_name
            FROM inventory_embeddings
            ORDER BY embedding <#> :embedding
            LIMIT :k
            """
        )
        with self.db.engine.connect() as conn:
            rows = conn.execute(sql, {"embedding": embedding, "k": self.top_k}).fetchall()
        if not rows:
            logger.info("Vector search found no matches; falling back to LLM without context")
            return self.llm_manager.generate(user_request, chat_history)
        context_lines = [f"{r.store}: {r.product_name} by {r.brand_name}" for r in rows]
        context = "\n".join(context_lines)
        return self.llm_manager.generate(user_request, chat_history, context=context)
