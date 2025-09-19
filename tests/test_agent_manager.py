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
    def __init__(self, response: str = "dummy"):
        self.response = response
        self.last_context = None
        self.last_user_request = None

    def generate(self, user_request, chat_history, context=None):
        self.last_user_request = user_request
        self.last_context = context
        return self.response


class DummyAgent(AgentBase):
    def __init__(self, score: float, response: str):
        self._score = score
        self._response = response

    def score_request(self, user_request, chat_history):
        return self._score

    def handle(self, user_request, chat_history, **_):
        return self._response


def _manager_with_agents(*agents, llm=None):
    llm_impl = llm or DummyLLM()
    llm_mgr = LLMManager({}, llm_impl)
    evaluator = ResponseEvaluator(threshold=0.5)
    general = GeneralChatAgent(llm_mgr)
    manager = AgentManager(
        llm_mgr,
        agents=list(agents),
        evaluator=evaluator,
        general_agent=general,
    )
    return manager, llm_impl


def test_general_agent_receives_specialist_context():
    agent_one = DummyAgent(0.9, "First specialist answer")
    agent_two = DummyAgent(0.4, "Second specialist answer")
    manager, llm = _manager_with_agents(agent_one, agent_two, llm=DummyLLM("final"))
    history = [("user", "request")]

    response = manager.handle_request("request", history)

    assert response == "final"
    assert llm.last_context is not None
    assert "First specialist answer" in llm.last_context
    assert "Second specialist answer" in llm.last_context
    assert "validated findings" in llm.last_context.lower()
    trace = manager.get_last_trace()
    assert trace is not None
    assert trace["user_request"] == "request"
    assert trace["final_response"] == "final"
    assert trace["final_response_source"] == "general"
    assert trace["llm"]["class"] == "DummyLLM"


def test_falls_back_to_best_specialist_when_general_fails():
    class FailingLLM:
        def generate(self, user_request, chat_history, context=None):
            raise RuntimeError("boom")

    llm_mgr = LLMManager({}, FailingLLM())
    general = GeneralChatAgent(llm_mgr)
    evaluator = ResponseEvaluator(threshold=0.5)
    manager = AgentManager(
        llm_mgr,
        agents=[
            DummyAgent(1.0, "No results found."),
            DummyAgent(0.8, "Here is the data you need."),
        ],
        evaluator=evaluator,
        general_agent=general,
    )
    history = [("user", "hello")]

    response = manager.handle_request("hello", history)

    assert response == "Here is the data you need."
    trace = manager.get_last_trace()
    assert trace is not None
    assert trace["final_response_source"] == "specialist"
    assert trace["fallback_used"] is True
    assert "language model is unavailable" in trace["general"]["response"]
    assert trace["general"]["error"] is None


def test_handle_request_requires_chat_history():
    manager, _ = _manager_with_agents(DummyAgent(1.0, "ok"))
    with pytest.raises(ValueError):
        manager.handle_request("request", [])


def test_handle_request_return_trace_flag():
    agent = DummyAgent(0.8, "Specialist reply")
    manager, llm = _manager_with_agents(agent, llm=DummyLLM("general"))
    history = [("user", "what's up?")]

    response, trace = manager.handle_request("what's up?", history, return_trace=True)

    assert response == "general"
    assert trace["user_request"] == "what's up?"
    assert trace["llm"]["class"] == "DummyLLM"
    assert trace["specialists"][0]["response"] == "Specialist reply"
    assert trace["final_response_source"] == "general"
    # Ensure the stored trace is not affected by external mutation
    trace["user_request"] = "mutated"
    assert manager.get_last_trace()["user_request"] == "what's up?"
