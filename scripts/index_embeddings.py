"""Populate the ``inventory_embeddings`` table with vector representations."""
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
    df = db.query_df("SELECT store, product_name, brand_name FROM app_inventory")
    if df.empty:
        print("No products to embed")
        return
    texts = [f"{row.store}: {row.product_name} by {row.brand_name}" for _, row in df.iterrows()]
    vectors = embedder.embed_documents(texts)
    insert = text(
        """
        INSERT INTO inventory_embeddings (store, product_name, brand_name, embedding)
        VALUES (:store, :product_name, :brand_name, :embedding)
        """
    )
    with db.engine.begin() as conn:
        for row, vec in zip(df.itertuples(), vectors):
            conn.execute(
                insert,
                {
                    "store": row.store,
                    "product_name": row.product_name,
                    "brand_name": row.brand_name,
                    "embedding": vec,
                },
            )
    print(f"Inserted {len(vectors)} embeddings")


if __name__ == "__main__":
    main()
