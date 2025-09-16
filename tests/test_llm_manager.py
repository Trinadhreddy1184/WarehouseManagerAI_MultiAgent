"""Tests for the LLMManager and context handling."""
from __future__ import annotations

import pytest

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


def test_from_config_disabled_when_flag_missing(monkeypatch):
    monkeypatch.delenv("ENABLE_LLM", raising=False)
    manager = LLMManager.from_config({})
    assert not manager.is_enabled()
    with pytest.raises(RuntimeError):
        manager.generate("hello", [])
