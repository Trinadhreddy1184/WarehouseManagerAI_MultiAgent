"""Tests for the LLMManager and context handling."""
from __future__ import annotations

import pytest

from src.llm import manager as manager_mod
from src.llm.manager import LLMManager


class DummyLLM:
    def __init__(self) -> None:
        self.called_with = None

    def generate(self, user_request, chat_history, context=None):
        self.called_with = (user_request, chat_history, context)
        return "ok"


def test_generate_with_context():
    llm = DummyLLM()
    manager = LLMManager({}, llm)
    manager.generate("hi", [("user", "hi")], context="ctx")
    assert llm.called_with == ("hi", [("user", "hi")], "ctx")


def test_generate_requires_history():
    llm = DummyLLM()
    manager = LLMManager({}, llm)
    with pytest.raises(ValueError):
        manager.generate("hi", [])


def test_get_embedding_uses_config(monkeypatch):
    created = []

    class DummyEmbedding:
        def __init__(self, model_id=None, region=None):
            created.append((model_id, region))

        def embed_query(self, text):  # pragma: no cover - helper interface
            return [0.0]

    monkeypatch.setattr(manager_mod, "EmbeddingManager", DummyEmbedding)

    cfg = {
        "bedrock": {"region_name": "us-west-2"},
        "embedding": {"model_id": "custom", "region_name": "eu-west-1"},
    }
    mgr = manager_mod.LLMManager(cfg, DummyLLM())

    emb1 = mgr.get_embedding()
    emb2 = mgr.get_embedding()

    assert emb1 is emb2
    assert created == [("custom", "eu-west-1")]
