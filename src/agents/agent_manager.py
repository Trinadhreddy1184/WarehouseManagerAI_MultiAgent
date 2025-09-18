"""Coordinator for multi-agent routing.

The agent manager keeps a list of available agents and delegates user
requests to the highest scoring agent. If multiple agents tie on the
highest score it picks the first. Agents are expected to implement the
score/handle interface defined in :mod:`src.agents.base`.
"""
from __future__ import annotations

from typing import List, Tuple, Optional
import logging
from .base import AgentBase
from .product_lookup_agent import ProductLookupAgent
from .vector_search_agent import VectorSearchAgent
from .general_chat_agent import GeneralChatAgent
from .response_evaluator import ResponseEvaluator
from .sql_query_agent import SqlQueryAgent
from src.llm.manager import LLMManager

logger = logging.getLogger(__name__)

class AgentManager:
    def __init__(self, llm_manager: LLMManager, *,
                 agents: Optional[List[AgentBase]] = None,
                 evaluator: Optional[ResponseEvaluator] = None) -> None:
        """Create a new agent manager.

        Parameters
        ----------
        llm_manager : LLMManager
            Manager used to construct default agents.
        agents : Optional[List[AgentBase]]
            If provided, use this list of agents instead of the defaults. The
            list is expected to be ordered by preference.
        evaluator : ResponseEvaluator
            Scorer used to judge whether an agent's response is satisfactory.
        """
        self.llm_manager = llm_manager
        self.agents: List[AgentBase] = agents or [
            SqlQueryAgent(llm_manager),
            ProductLookupAgent(),
            VectorSearchAgent(llm_manager),
            GeneralChatAgent(llm_manager)
        ]
        self.evaluator = evaluator or ResponseEvaluator()
        logger.debug(
            "AgentManager initialised with agents=%s evaluator_threshold=%s",
            [type(a).__name__ for a in self.agents],
            self.evaluator.threshold,
        )

    def handle_request(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
    ) -> str:
        """Dispatch a user request to the most appropriate agent.

        Agents are tried in order of their relevance score. After each
        response an evaluator determines whether the answer is acceptable. If
        not, the next best agent is attempted. The last response is returned
        even if it fails evaluation to ensure the user receives some output.

        Parameters
        ----------
        user_request : str
            Latest utterance from the user.
        chat_history : List[Tuple[str, str]]
            Full conversation including the latest user message. The manager
            requires at least one entry so agents can ground their responses
            in context instead of starting from a blank state.
        """
        logger.info("Handling user request: %s", user_request)
        if not chat_history:
            raise ValueError("chat_history must contain at least the current user message")
        history = list(chat_history)
        scores = [
            (agent, agent.score_request(user_request, history))
            for agent in self.agents
        ]
        logger.debug("Agent scores: %s", [(type(a).__name__, s) for a, s in scores])
        scores.sort(key=lambda item: item[1], reverse=True)
        last_response = ""
        for agent, _score in scores:
            logger.debug("Trying agent %s", type(agent).__name__)
            try:
                response = agent.handle(user_request, history)
            except Exception as exc:
                logger.exception("Agent %s failed: %s", type(agent).__name__, exc)
                continue
            score = self.evaluator.evaluate(user_request, response)
            logger.debug("Evaluator score for agent %s: %s", type(agent).__name__, score)
            if score >= self.evaluator.threshold:
                logger.info("Agent %s satisfied the request", type(agent).__name__)
                return response
            last_response = response
        logger.warning("All agents failed evaluation; returning last response")
        return last_response

