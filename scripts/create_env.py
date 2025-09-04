"""Utility to generate a .env file with required environment variables.

Existing .env file is backed up to .env.bak before writing a new one.
"""
from __future__ import annotations

from pathlib import Path
import os

ENV_CONTENT = """# Auto-generated environment configuration
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v1
S3_BUCKET=your-bucket
S3_KEY=path/to/dump.sql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=warehouse
DB_USER=app
DB_PASSWORD=app_pw
DATABASE_URL=postgresql://app:app_pw@localhost:5432/warehouse
"""


def main() -> None:
    path = Path(".env")
    if path.exists():
        backup = Path(".env.bak")
        path.rename(backup)
    path.write_text(ENV_CONTENT)
    os.chmod(path, 0o600)
    print(".env file written. Previous version backed up to .env.bak if it existed.")


if __name__ == "__main__":
    main()
