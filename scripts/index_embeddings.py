"""Populate embeddings for products imported from the S3 inventory dump."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# from sqlalchemy import text

# Ensure ``src`` is importable when this script is executed directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from database.db_manager import get_db

try:  # Embedding generation is optional while the LLM is disabled
    from llm.embeddings import EmbeddingManager  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency guard
    EmbeddingManager = None  # type: ignore
    _EMBEDDINGS_IMPORT_ERROR = exc
else:  # pragma: no cover
    _EMBEDDINGS_IMPORT_ERROR = None

try:  # optional pgvector adapter
    from pgvector.sqlalchemy import register_vector  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    register_vector = None  # type: ignore


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def main() -> None:
    if not _env_flag("ENABLE_LLM", False) or EmbeddingManager is None:
        if EmbeddingManager is None and _EMBEDDINGS_IMPORT_ERROR is not None:
            print(
                f"Skipping embedding indexing – dependencies unavailable: {_EMBEDDINGS_IMPORT_ERROR}"
            )
        else:
            print("Skipping embedding indexing because LLM is disabled")
        return
    db = get_db()
    # if register_vector:
    #     register_vector(db.engine)
    embedder = EmbeddingManager()
    df = db.query_df(
        """
        SELECT p.id, p.product_name, b.brand_name
        FROM vip_products p
        LEFT JOIN vip_brands b ON p.vip_brand_id = b.vip_brand_id
        WHERE p.product_name IS NOT NULL
        """
    )
    if df.empty:
        print("No products to embed")
        return
    texts = [
        f"{row.product_name} by {row.brand_name or 'Unknown brand'}"
        for _, row in df.iterrows()
    ]
    vectors = embedder.embed_documents(texts)
    update_sql = """
        UPDATE vip_products
        SET embedding = :embedding
        WHERE id = :id
    """
    for row, vec in zip(df.itertuples(), vectors):
        db.execute(update_sql, {"id": row.id, "embedding": json.dumps(list(vec))})
    print(f"Indexed {len(vectors)} product embeddings")


if __name__ == "__main__":
    main()
