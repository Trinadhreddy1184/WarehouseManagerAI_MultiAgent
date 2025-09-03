"""Coordinator for multi‑agent routing.

The agent manager keeps a list of available agents and delegates user
requests to the highest scoring agent.  If multiple agents tie on the
highest score it picks the first.  Agents are expected to implement the
score/handle interface defined in :mod:`src.agents.base`.
"""
from __future__ import annotations

from typing import List, Tuple, Optional

from .base import AgentBase
from .product_lookup_agent import ProductLookupAgent
from .general_chat_agent import GeneralChatAgent
from .response_evaluator import ResponseEvaluator

from src.llm.manager import LLMManager



class AgentManager:
    def __init__(self, llm_manager: LLMManager, *,
                 agents: Optional[List[AgentBase]] = None,
                 evaluator: Optional[ResponseEvaluator] = None) -> None:
        """Create a new agent manager.

        Parameters
        ----------
        llm_manager: LLMManager
            Manager used to construct default agents.
        agents: optional list of AgentBase
            If provided, use this list of agents instead of the defaults.  The
            list is expected to be ordered by preference.
        evaluator: ResponseEvaluator
            Scorer used to judge whether an agent's response is satisfactory.
        """
        self.llm_manager = llm_manager
        self.agents: List[AgentBase] = agents or [
            ProductLookupAgent(),
            GeneralChatAgent(llm_manager),
        ]
        self.evaluator = evaluator or ResponseEvaluator()

    def handle_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        """Dispatch a user request to the most appropriate agent.

        Agents are tried in order of their relevance score.  After each
        response an evaluator determines whether the answer is acceptable.  If
        not, the next best agent is attempted.  The last response is returned
        even if it fails evaluation to ensure the user receives some output.
        """
        scores = [(agent, agent.score_request(user_request, chat_history)) for agent in self.agents]
        scores.sort(key=lambda item: item[1], reverse=True)
        last_response = ""
        for agent, _score in scores:
            try:
                response = agent.handle(user_request, chat_history)
            except Exception:
                continue
            if self.evaluator.evaluate(user_request, response) >= self.evaluator.threshold:
                return response
            last_response = response
        return last_response
