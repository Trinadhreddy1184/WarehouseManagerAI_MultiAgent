#!/usr/bin/env python
"""Basic connectivity test for the database and LLM using real inventory data.

The check now verifies that the S3-imported liquor and wine tables are present
and populated.  It fetches a sample product from ``vip_products`` joined with
``vip_brands`` and asks the LLM to generate a short blurb about it.  This
ensures both the database and LLM can operate on the actual inventory data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project ``src`` directory is on the Python path when executed
# directly from the repository root or an installed location.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.logging_config import setup_logging  # noqa: E402
from config.load_config import load_llm_config  # noqa: E402
from database.db_manager import get_db  # noqa: E402
from llm.manager import LLMManager  # noqa: E402


def main() -> None:
    """Run the sanity checks."""
    setup_logging()

    # Database: ensure core tables exist and contain data
    db = get_db()
    count_df = db.query_df("SELECT COUNT(*) AS count FROM vip_products")
    product_count = int(count_df.loc[0, "count"])
    if product_count == 0:
        raise RuntimeError("vip_products table is empty – check SQL import")

    sample_df = db.query_df(
        """
        SELECT p.product_name, b.brand_name
        FROM vip_products p
        JOIN vip_brands b ON b.vip_brand_id = p.vip_brand_id
        WHERE p.product_name IS NOT NULL
        LIMIT 1
        """
    )
    product_name = sample_df.loc[0, "product_name"]
    brand_name = sample_df.loc[0, "brand_name"]
    print(f"Found {product_count} products; example: {brand_name} {product_name}")

    # LLM: generate a response based on the sample product
    llm_config_path = os.getenv("LLM_CONFIG_PATH", "src/config/llm_config.yaml")
    llm = LLMManager.from_config(load_llm_config(llm_config_path))
    prompt = f"Provide a short marketing blurb for {product_name} by {brand_name}."
    response = llm.generate(prompt, [])
    print("LLM response:", response)

    print("Sanity check passed.")


if __name__ == "__main__":
    main()

