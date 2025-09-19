"""Simple response evaluator used for agent rerouting.

The evaluator assigns a score between 0 and 1 indicating how helpful a
response is.  The default implementation uses a few lightweight heuristics
so that tests can run without external LLM calls.  Responses that contain
apologetic or failure phrases receive a low score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import logging


logger = logging.getLogger(__name__)


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
    FAILURE_PATTERNS = (
        r"i'm sorry",
        r"i am sorry",
        r"couldn't",
        r"cannot",
        r"can't",
        r"no results found",
        r"no products found",
        r"language model is unavailable",
        r"i don't know",
        r"i do not know",
        r"not sure",
        r"unable to",
        r"no information",
        r"please try again",
    )

    def evaluate(self, user_request: str, response: str) -> float:
        """Return a score in [0, 1] for the supplied response."""
        if not response or not response.strip():
            logger.debug("ResponseEvaluator: empty response detected")
            return 0.0

        text = response.lower()
        if any(re.search(pat, text) for pat in self.FAILURE_PATTERNS):
            logger.debug(
                "ResponseEvaluator: detected failure pattern in %s", response
            )
            return 0.0
        else:
            logger.debug("ResponseEvaluator: response deemed acceptable")
            return 1.0
