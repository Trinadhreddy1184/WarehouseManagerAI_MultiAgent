"""Base definitions for agents.

Agents encapsulate specialised knowledge or behaviour.  Each agent can
determine whether it is appropriate to handle a given user request by
returning a relevance score between 0 and 1, and then generating a
response if selected.
"""
from __future__ import annotations

import abc
from typing import List, Tuple, Any


class AgentBase(abc.ABC):
    """Abstract base class for all agents."""

    @abc.abstractmethod
    def score_request(self, user_request: str, chat_history: List[Tuple[str, str]]) -> float:
        """Return a score between 0 and 1 indicating how well this agent can handle the request."""
        raise NotImplementedError

    @abc.abstractmethod
    def handle(self, user_request: str, chat_history: List[Tuple[str, str]]) -> str:
        """Generate a response to the user's request."""
        raise NotImplementedError


class AgentException(Exception):
    """Custom exception raised when an agent encounters an unrecoverable error."""
    pass
