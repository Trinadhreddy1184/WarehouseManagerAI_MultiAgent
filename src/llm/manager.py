"""Central manager for large language models.

This class hides the details of interacting with a specific provider
(Amazon Bedrock in this project) and exposes a simple generate API.  At
initialisation time it builds the appropriate wrapper based on a config
dictionary.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import logging
import os

logger = logging.getLogger(__name__)

try:  # Optional Bedrock dependency – unavailable when the LLM is disabled
    from .bedrock import BedrockLLM  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency guard
    BedrockLLM = None  # type: ignore
    _BEDROCK_IMPORT_ERROR: Optional[Exception] = exc
else:  # pragma: no cover - executed only when dependency is present
    _BEDROCK_IMPORT_ERROR = None

try:  # Embeddings are also optional in DuckDB-only mode
    from .embeddings import EmbeddingManager as _EmbeddingManager  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency guard
    _EmbeddingManager = None  # type: ignore
    _EMBEDDINGS_IMPORT_ERROR: Optional[Exception] = exc
else:  # pragma: no cover
    _EMBEDDINGS_IMPORT_ERROR = None


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


class _DisabledLLM:
    """Placeholder client used when Bedrock access is disabled."""

    def generate(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
        context: str | None = None,
    ) -> str:
        raise RuntimeError("LLM access is disabled in DuckDB-only mode")

    def __repr__(self) -> str:  # pragma: no cover - representational helper
        return "<DisabledLLM>"


class LLMManager:
    """Entry point for working with LLMs.

    Parameters
    ----------
    config : dict
        Dictionary parsed from ``llm_config.yaml``.  It must contain a
        ``llm`` section with model parameters and a ``bedrock`` section with
        AWS region information.
    llm : object
        Low-level client implementing a ``generate(user_request, chat_history)``
        method.  Consumers should rarely instantiate this class directly –
        instead call :meth:`from_config`.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm: Any,
        *,
        embedding_manager: Optional[Any] = None,
    ) -> None:
        self.config = config
        self.llm = llm or _DisabledLLM()
        self._embedding_manager = embedding_manager
        self._enabled = not isinstance(self.llm, _DisabledLLM)

        logger.debug(
            "LLMManager initialised with config: %s | enabled=%s",
            config,
            self._enabled,
        )

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "LLMManager":
        """Instantiate the manager from a configuration dictionary."""
        # Currently we only support Bedrock models.  Additional providers can
        # be added here.

        logger.info("Creating LLMManager from config")

        enable_llm = _env_flag("ENABLE_LLM", False)
        if not enable_llm or BedrockLLM is None:
            if not enable_llm:
                logger.info("ENABLE_LLM not set – returning disabled LLM manager")
            elif _BEDROCK_IMPORT_ERROR is not None:
                logger.warning(
                    "Bedrock client unavailable (%s); running with disabled LLM",
                    _BEDROCK_IMPORT_ERROR,
                )
            return cls(config, _DisabledLLM())

        llm = BedrockLLM(config)  # type: ignore[misc]
        embedding_manager: Optional[Any] = None
        if _EmbeddingManager is not None:
            embedding_manager = _EmbeddingManager()
        elif _EMBEDDINGS_IMPORT_ERROR is not None:
            logger.warning(
                "Embedding manager unavailable (%s); vector features disabled",
                _EMBEDDINGS_IMPORT_ERROR,
            )
        return cls(config, llm, embedding_manager=embedding_manager)

    def is_enabled(self) -> bool:
        """Return ``True`` when a real LLM backend is configured."""

        return self._enabled

    def get_embedding(self):
        """Return the embedding helper if available."""

        if not self._enabled or self._embedding_manager is None:
            raise RuntimeError(
                "Embedding model is unavailable because the LLM is disabled"
            )
        return self._embedding_manager

    def generate(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]] | None = None,
        *,
        context: str | None = None,
    ) -> str:
        """Generate a response from the underlying LLM."""

        logger.info("Generating response for request: %s", user_request)
        if not self._enabled:
            raise RuntimeError("LLM access is disabled")
        response = self.llm.generate(user_request, chat_history or [], context=context)
        logger.debug("LLMManager received response: %s", response)
        return response
