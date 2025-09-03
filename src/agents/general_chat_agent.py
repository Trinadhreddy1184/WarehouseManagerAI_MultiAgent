"""Fallback agent for general chat and unhandled requests.

This agent delegates directly to the underlying LLM via the provided
LLMManager.  It always returns a moderate score so that it will be
selected when no specialist agent claims the request.
"""
from __future__ import annotations

from typing import List, Tuple

from .base import AgentBase
from src.llm.manager import LLMManager


class GeneralChatAgent(AgentBase):
    def __init__(self, llm_manager: LLMManager) -> None:
        self.llm_manager = llm_manager

    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        # Always return a baseline score.  This agent is a catch‑all.
        return 0.5

    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        # Simply forward the request to the LLM
        return self.llm_manager.generate(user_request, chat_history)
