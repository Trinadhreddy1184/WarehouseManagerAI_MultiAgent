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
        DummyAgent(1.0, "No results found."),
        DummyAgent(0.5, "success"),
    )
    history = [("user", "request")]
    assert manager.handle_request("request", history) == "success"


def test_returns_first_satisfactory_response():
    manager = _manager_with_agents(
        DummyAgent(1.0, "all good"),
        DummyAgent(0.5, "fallback"),
    )
    history = [("user", "request")]
    assert manager.handle_request("request", history) == "all good"


def test_general_chat_returns_error_when_llm_unavailable():
    class FailingLLM:
        def generate(self, user_request, chat_history, context=None):
            raise RuntimeError("boom")

    llm_mgr = LLMManager({}, FailingLLM())
    agent = GeneralChatAgent(llm_mgr)
    manager = AgentManager(llm_mgr, agents=[agent])
    history = [("user", "hello")]
    response = manager.handle_request("hello", history)
    assert "language model is unavailable" in response.lower()


def test_handle_request_requires_chat_history():
    manager = _manager_with_agents(DummyAgent(1.0, "ok"))
    with pytest.raises(ValueError):
        manager.handle_request("request", [])
