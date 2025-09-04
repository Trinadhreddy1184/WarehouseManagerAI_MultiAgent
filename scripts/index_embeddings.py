"""Populate the ``inventory_embeddings`` table with vector representations."""
from __future__ import annotations

from sqlalchemy import text

from src.database.db_manager import get_db
from src.llm.embeddings import EmbeddingManager


def main() -> None:
    db = get_db()
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
