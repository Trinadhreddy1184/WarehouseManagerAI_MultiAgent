"""Coordinator for multi-agent routing.

The agent manager keeps a list of specialist agents and a single
general-purpose chat agent. Every user request is fanned out to the
specialists. Their responses are then summarised and passed to the
general chat agent, which produces the final reply for the user.
Agents are expected to implement the score/handle interface defined in
:mod:`src.agents.base`.
"""
from __future__ import annotations

import copy
from typing import List, Tuple, Optional, Dict, Any
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
    def __init__(
        self,
        llm_manager: LLMManager,
        *,
        agents: Optional[List[AgentBase]] = None,
        evaluator: Optional[ResponseEvaluator] = None,
        general_agent: Optional[GeneralChatAgent] = None,
    ) -> None:
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
        if not hasattr(self.llm_manager.llm, "generate"):
            raise ValueError("llm_manager.llm must implement a generate method")

        provided_agents: List[AgentBase] = list(agents) if agents is not None else [
            SqlQueryAgent(llm_manager),
            ProductLookupAgent(),
            VectorSearchAgent(llm_manager),
        ]

        selected_general = general_agent
        if selected_general is None:
            for candidate in list(provided_agents):
                if isinstance(candidate, GeneralChatAgent):
                    selected_general = candidate
                    provided_agents.remove(candidate)
                    break
        if selected_general is None:
            selected_general = GeneralChatAgent(llm_manager)

        self.general_agent: GeneralChatAgent = selected_general
        self.specialist_agents: List[AgentBase] = provided_agents
        self.agents: List[AgentBase] = self.specialist_agents + [self.general_agent]
        self.evaluator = evaluator or ResponseEvaluator()
        self.last_trace: Optional[Dict[str, Any]] = None
        logger.debug(
            "AgentManager initialised with specialists=%s general=%s evaluator_threshold=%s",
            [type(a).__name__ for a in self.specialist_agents],
            type(self.general_agent).__name__,
            self.evaluator.threshold,
        )

    def handle_request(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
        *,
        return_trace: bool = False,
    ) -> str | Tuple[str, Dict[str, Any]]:
        """Dispatch a user request through all specialist agents.

        Each specialist agent is asked to score and respond to the request.
        Their answers, scores and evaluator feedback are collated into a
        context block supplied to the general chat agent. The general agent
        synthesises the final response for the user. If the general agent
        fails, the best specialist response (based on evaluator score) is
        returned instead.

        Parameters
        ----------
        user_request : str
            Latest utterance from the user.
        chat_history : List[Tuple[str, str]]
            Full conversation including the latest user message. The manager
            requires at least one entry so agents can ground their responses
            in context instead of starting from a blank state.
        return_trace : bool, optional
            When ``True`` the method returns a tuple ``(response, trace)``
            where ``trace`` contains a structured log of the orchestration
            steps. The default behaviour (``False``) returns only the final
            response string.
        """
        logger.info("Handling user request: %s", user_request)
        if not chat_history:
            raise ValueError("chat_history must contain at least the current user message")
        history = list(chat_history)
        trace_data: Dict[str, Any] = {
            "user_request": user_request,
            "chat_history": copy.deepcopy(history),
            "llm": self._build_llm_trace(),
            "specialists": [],
            "context": None,
            "general": None,
            "final_response": None,
            "final_response_source": None,
            "fallback_used": False,
        }

        agent_records: List[Dict[str, Any]] = []
        for agent in self.specialist_agents:
            record: Dict[str, Any] = {
                "agent": agent,
                "name": type(agent).__name__,
                "score": 0.0,
                "status": "pending",
            }
            trace_entry: Dict[str, Any] = {
                "name": record["name"],
                "score": 0.0,
                "status": "pending",
                "response": None,
                "evaluation": None,
                "error": None,
            }
            record["trace"] = trace_entry
            try:
                relevance = agent.score_request(user_request, history)
                record["score"] = relevance
                trace_entry["score"] = relevance
            except Exception as exc:
                logger.exception("Agent %s failed during scoring: %s", type(agent).__name__, exc)
                message = f"Scoring failed: {exc}"
                record["status"] = "error"
                record["error"] = message
                trace_entry["status"] = "error"
                trace_entry["error"] = message
                agent_records.append(record)
                continue
            agent_records.append(record)

        agent_records.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        best_response = ""
        best_eval = float("-inf")

        for record in agent_records:
            if record.get("status") == "error":
                continue
            agent = record["agent"]
            trace_entry = record.get("trace", {})
            logger.debug("Collecting response from agent %s", record["name"])
            try:
                response = agent.handle(user_request, history)
                record["response"] = response
                trace_entry["response"] = response
            except Exception as exc:
                logger.exception("Agent %s failed while handling request: %s", record["name"], exc)
                message = f"Execution failed: {exc}"
                record["status"] = "error"
                record["error"] = message
                trace_entry["status"] = "error"
                trace_entry["error"] = message
                continue
            evaluation = self.evaluator.evaluate(user_request, response)
            record["evaluation"] = evaluation
            trace_entry["evaluation"] = evaluation
            if evaluation >= self.evaluator.threshold:
                record["status"] = "success"
                trace_entry["status"] = "success"
            else:
                record["status"] = "low_confidence"
                trace_entry["status"] = "low_confidence"
            if evaluation > best_eval:
                best_eval = evaluation
                best_response = response

        context_lines = [
            "You are the general chat agent responsible for synthesising the specialist",
            "agents' findings into a final answer for the user.",
            "Follow these rules:",
            "1. Use the factual data from specialists when available.",
            "2. Combine consistent insights into a single clear response.",
            "3. Highlight uncertainties or missing data if every agent failed.",
            "4. Keep the tone professional and helpful.",
            "",
            f"User request: {user_request}",
            "",
            "Specialist agent outputs:",
        ]

        if not agent_records:
            context_lines.append("(No specialist agents produced responses.)")

        for record in agent_records:
            name = record.get("name", "UnknownAgent")
            score = record.get("score", 0.0)
            status = record.get("status", "no_response")
            evaluation = record.get("evaluation")
            status_fragments = [f"relevance={score:.2f}"]
            if evaluation is not None:
                status_fragments.append(f"quality={evaluation:.2f}")
            status_line = f"- {name} ({', '.join(status_fragments)}): {status}"
            context_lines.append(status_line)
            detail = record.get("response") or record.get("error") or "(no response)"
            context_lines.append(detail.strip())
            context_lines.append("")

        synthesis_context = "\n".join(context_lines).strip()
        trace_data["context"] = synthesis_context
        trace_data["specialists"] = [
            copy.deepcopy(record.get("trace", {})) for record in agent_records
        ]

        final_response: str
        final_source = "general"
        general_response: Optional[str] = None
        general_score: Optional[float] = None
        try:
            general_response = self.general_agent.handle(
                user_request,
                history,
                context=synthesis_context,
            )
            logger.info("General agent produced final response")
            general_score = self.evaluator.evaluate(user_request, general_response)
            trace_data["general"] = {
                "response": general_response,
                "evaluation": general_score,
                "error": None,
            }
            if general_score < self.evaluator.threshold and best_response:
                logger.warning(
                    "General agent response scored %.2f; using best specialist response",
                    general_score,
                )
                final_response = best_response
                final_source = "specialist"
            else:
                final_response = general_response
        except Exception as exc:
            logger.exception("General chat agent failed: %s", exc)
            if best_response:
                logger.warning("Falling back to best specialist response")
                final_response = best_response
                final_source = "specialist"
            else:
                logger.error("No specialist responses available; returning fallback message")
                final_response = "I'm unable to answer that right now. Please try again later."
                final_source = "fallback"
            trace_data["general"] = {
                "response": general_response,
                "evaluation": general_score,
                "error": str(exc),
            }

        if trace_data.get("general") is None:
            trace_data["general"] = {
                "response": general_response,
                "evaluation": general_score,
                "error": None,
            }

        trace_data["final_response"] = final_response
        trace_data["final_response_source"] = final_source
        trace_data["fallback_used"] = final_source != "general"

        self.last_trace = copy.deepcopy(trace_data)

        if return_trace:
            return final_response, copy.deepcopy(trace_data)
        return final_response

    def _build_llm_trace(self) -> Dict[str, Any]:
        """Return a snapshot describing the active LLM configuration."""

        summary: Dict[str, Any] = {
            "class": type(self.llm_manager.llm).__name__,
            "has_generate": callable(getattr(self.llm_manager.llm, "generate", None)),
        }
        config = getattr(self.llm_manager, "config", None)
        if isinstance(config, dict):
            try:
                summary["config"] = copy.deepcopy(config)
            except Exception:  # pragma: no cover - defensive copying
                summary["config"] = dict(config)
        else:
            summary["config"] = {}
        return summary

    def get_last_trace(self) -> Optional[Dict[str, Any]]:
        """Return the most recent orchestration trace."""

        if self.last_trace is None:
            return None
        return copy.deepcopy(self.last_trace)
