"""Populate embeddings for products imported from the S3 inventory dump."""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

# Ensure ``src`` is importable when this script is executed directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from database.db_manager import get_db
from llm.embeddings import EmbeddingManager

try:  # optional pgvector adapter
    from pgvector.sqlalchemy import register_vector  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    register_vector = None  # type: ignore


def main() -> None:
    db = get_db()
    if register_vector:
        register_vector(db.engine)
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
    update = text(
        """
        UPDATE vip_products
        SET embedding = :embedding
        WHERE id = :id
        """
    )
    with db.engine.begin() as conn:
        for row, vec in zip(df.itertuples(), vectors):
            conn.execute(update, {"id": row.id, "embedding": vec})
    print(f"Indexed {len(vectors)} product embeddings")


if __name__ == "__main__":
    main()
