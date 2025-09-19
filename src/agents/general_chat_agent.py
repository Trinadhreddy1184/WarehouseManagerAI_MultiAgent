"""Fallback agent for general chat and unhandled requests.

This agent delegates directly to the underlying LLM via the provided
LLMManager.  It always returns a moderate score so that it will be
selected when no specialist agent claims the request.
"""
from __future__ import annotations

from typing import List, Tuple

import logging

from .base import AgentBase
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)



class GeneralChatAgent(AgentBase):
    def __init__(self, llm_manager: LLMManager) -> None:
        self.llm_manager = llm_manager

    def score_request(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
    ) -> float:

        logger.debug("GeneralChatAgent scoring request: %s", user_request)

        # Always return a baseline score.  This agent is a catch‑all.
        return 0.5

    def handle(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
        *,
        context: str | None = None,
        **_: object,
    ) -> str:

        """Generate a response via the underlying LLM.

        If the model backend is misconfigured or unavailable the underlying
        call can raise an exception (for example when AWS credentials are
        missing).  Instead of bubbling the error up and allowing the
        AgentManager to silently fall back to another agent, return a clear
        message so the user understands why no answer was produced.
        """
        logger.info("GeneralChatAgent handling request")
        if not chat_history:
            raise ValueError("chat_history must include the current user request")
        try:
            response = self.llm_manager.generate(
                user_request,
                chat_history,
                context=context,
            )
            logger.debug("LLM response: %s", response)
            return response
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("LLM generation failed: %s", exc)
            return (
                "The language model is unavailable. Please verify your AWS "
                "credentials and Bedrock configuration."
            )

