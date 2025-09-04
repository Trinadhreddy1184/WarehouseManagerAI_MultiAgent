import os
import sys
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.agent_manager import AgentManager
from src.agents.base import AgentBase
from src.agents.response_evaluator import ResponseEvaluator
from src.agents.general_chat_agent import GeneralChatAgent
from src.llm.manager import LLMManager


class DummyLLM:
    def generate(self, user_request, chat_history, context=None):
        return "dummy"


class DummyAgent(AgentBase):
    def __init__(self, score: float, response: str):
        self._score = score
        self._response = response

    def score_request(self, user_request, chat_history):
        return self._score

    def handle(self, user_request, chat_history):
        return self._response


def _manager_with_agents(*agents):
    llm_mgr = LLMManager({}, DummyLLM())
    evaluator = ResponseEvaluator(threshold=0.5)
    return AgentManager(llm_mgr, agents=list(agents), evaluator=evaluator)


def test_falls_back_when_response_scores_low():
    manager = _manager_with_agents(
        DummyAgent(1.0, "I'm sorry, can't do that"),
        DummyAgent(0.5, "success"),
    )
    assert manager.handle_request("request", []) == "success"


def test_returns_first_satisfactory_response():
    manager = _manager_with_agents(
        DummyAgent(1.0, "all good"),
        DummyAgent(0.5, "fallback"),
    )
    assert manager.handle_request("request", []) == "all good"


def test_general_chat_returns_error_when_llm_unavailable():
    class FailingLLM:
        def generate(self, user_request, chat_history, context=None):
            raise RuntimeError("boom")

    llm_mgr = LLMManager({}, FailingLLM())
    agent = GeneralChatAgent(llm_mgr)
    manager = AgentManager(llm_mgr, agents=[agent])
    response = manager.handle_request("hello", [])
    assert "language model is unavailable" in response.lower()
