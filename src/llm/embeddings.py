"""Helpers for generating text embeddings via Amazon Bedrock."""
from __future__ import annotations

import os
from typing import List

from langchain_aws.embeddings import BedrockEmbeddings


class EmbeddingManager:
    """Simple wrapper around Bedrock's embedding models."""

    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        self.model_id = model_id or os.getenv(
            "BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1"
        )
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.client = BedrockEmbeddings(model_id=self.model_id, region_name=self.region)

    def embed_query(self, text: str) -> List[float]:
        """Return the embedding vector for a single piece of text."""
        return self.client.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings for a list of texts."""
        return self.client.embed_documents(texts)
