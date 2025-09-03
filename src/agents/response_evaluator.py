"""Simple response evaluator used for agent rerouting.

The evaluator assigns a score between 0 and 1 indicating how helpful a
response is.  The default implementation uses a few lightweight heuristics
so that tests can run without external LLM calls.  Responses that contain
apologetic or failure phrases receive a low score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ResponseEvaluator:
    """Heuristic response scorer.

    Parameters
    ----------
    threshold: float
        Minimum acceptable score.  AgentManager will fall back to another
        agent if a response scores below this value.
    """

    threshold: float = 0.5

    # Patterns that suggest the agent could not handle the request
    FAILURE_PATTERNS = (r"i'm sorry", r"couldn't", r"cannot")

    def evaluate(self, user_request: str, response: str) -> float:
        """Return a score in [0, 1] for the supplied response."""
        text = response.lower()
        if any(re.search(pat, text) for pat in self.FAILURE_PATTERNS):
            return 0.0
        return 1.0
