"""Central manager for large language models.

This class hides the details of interacting with a specific provider
(Amazon Bedrock in this project) and exposes a simple generate API.  At
initialisation time it builds the appropriate wrapper based on a config
dictionary.
"""
from __future__ import annotations

from typing import List, Tuple, Dict, Any, Optional

from .bedrock import BedrockLLM


class LLMManager:
    """Entry point for working with LLMs.

    Parameters
    ----------
    config : dict
        Dictionary parsed from ``llm_config.yaml``.  It must contain a
        ``llm`` section with model parameters and a ``bedrock`` section with
        AWS region information.
    llm : object
        Low‑level client implementing a ``generate(user_request, chat_history)``
        method.  Consumers should rarely instantiate this class directly –
        instead call :meth:`from_config`.
    """

    def __init__(self, config: Dict[str, Any], llm: Any):
        self.config = config
        self.llm = llm

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "LLMManager":
        """Instantiate the manager from a configuration dictionary."""
        # Currently we only support Bedrock models.  Additional providers can
        # be added here.
        llm = BedrockLLM(config)
        return cls(config, llm)

    def generate(self, user_request: str, chat_history: List[Tuple[str, str]] | None = None) -> str:
        """Generate a response from the underlying LLM.

        Parameters
        ----------
        user_request : str
            The raw query from the user.
        chat_history : List of (role, text) tuples
            Past conversation history in alternating roles.  If omitted an
            empty history is assumed.
        """
        return self.llm.generate(user_request, chat_history or [])
