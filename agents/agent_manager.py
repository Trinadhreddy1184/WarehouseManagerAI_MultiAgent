"""Coordinator for multi‑agent routing.

The agent manager keeps a list of available agents and delegates user
requests to the highest scoring agent.  If multiple agents tie on the
highest score it picks the first.  Agents are expected to implement the
score/handle interface defined in :mod:`src.agents.base`.
"""
from __future__ import annotations

from typing import List, Tuple

from .base import AgentBase
from .product_lookup_agent import ProductLookupAgent
from .general_chat_agent import GeneralChatAgent
from ..llm.manager import LLMManager


class AgentManager:
    def __init__(self, llm_manager: LLMManager) -> None:
        # Instantiate built‑in agents.  Custom agents can be added by
        # extending this list or by subclassing AgentManager.
        self.agents: List[AgentBase] = [
            ProductLookupAgent(),
            GeneralChatAgent(llm_manager),
        ]

    def handle_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        """Dispatch a user request to the most appropriate agent."""
        # Compute scores for each agent
        scores = [(agent, agent.score_request(user_request, chat_history)) for agent in self.agents]
        # Sort agents by descending score
        scores.sort(key=lambda item: item[1], reverse=True)
        best_agent, best_score = scores[0]
        try:
            return best_agent.handle(user_request, chat_history)
        except Exception as e:
            # Fall back to general chat if specialist agent fails
            for agent, _score in scores:
                if isinstance(agent, GeneralChatAgent):
                    return agent.handle(user_request, chat_history)
            # If no general chat agent exists, re‑raise
            raise
