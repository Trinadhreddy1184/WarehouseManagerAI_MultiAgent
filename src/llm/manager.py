"""Central manager for large language models.

This class hides the details of interacting with a specific provider
(Amazon Bedrock in this project) and exposes a simple generate API.  At
initialisation time it builds the appropriate wrapper based on a config
dictionary.
"""
from __future__ import annotations

from typing import List, Tuple, Dict, Any, Optional

import logging

from .bedrock import BedrockLLM
from .embeddings import EmbeddingManager

logger = logging.getLogger(__name__)

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
        self._embedding_manager: Optional[EmbeddingManager] = None

        logger.debug("LLMManager initialised with config: %s", config)


    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "LLMManager":
        """Instantiate the manager from a configuration dictionary."""
        # Currently we only support Bedrock models.  Additional providers can
        # be added here.

        logger.info("Creating LLMManager from config")

        llm = BedrockLLM(config)
        return cls(config, llm)

    def generate(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]] | None = None,
        *,
        context: str | None = None,
    ) -> str:
        """Generate a response from the underlying LLM.

        Parameters
        ----------
        user_request : str
            The raw query from the user.
        chat_history : List of (role, text) tuples
            Past conversation history in alternating roles. The list must
            include at least the latest user message so the LLM can ground the
            response in context.
        """

        logger.info("Generating response for request: %s", user_request)
        if not chat_history:
            raise ValueError("chat_history must include at least the current user request")
        response = self.llm.generate(user_request, chat_history, context=context)
        logger.debug("LLMManager received response: %s", response)
        return response

    def get_embedding(self) -> EmbeddingManager:
        """Return a cached embedding manager instance."""

        if self._embedding_manager is None:
            embed_conf = self.config.get("embedding", {}) if isinstance(self.config, dict) else {}
            model_id = None
            region = None
            if isinstance(embed_conf, dict):
                model_id = embed_conf.get("model_id")
                region = embed_conf.get("region_name")
            if not region:
                bedrock_conf = self.config.get("bedrock", {}) if isinstance(self.config, dict) else {}
                if isinstance(bedrock_conf, dict):
                    region = bedrock_conf.get("region_name")
            self._embedding_manager = EmbeddingManager(model_id=model_id, region=region)
            logger.debug(
                "Created EmbeddingManager model_id=%s region=%s",
                model_id or "(default)",
                region or "(default)",
            )
        return self._embedding_manager


