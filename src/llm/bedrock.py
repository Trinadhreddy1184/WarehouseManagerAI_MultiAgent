"""Wrapper around Amazon Bedrock models using LangChain.

This class encapsulates the logic for deciding which Bedrock API to call
(ChatBedrock vs. `converse`) based on the model ID, building prompts and
executing inference.  It exposes a simple ``generate`` method that
accepts the user query and conversation history and returns a plain text
response.
"""
from __future__ import annotations

import os
from typing import List, Tuple, Dict, Any
import logging

import boto3
from botocore.config import Config as BotoConfig

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

logger = logging.getLogger(__name__)

class BedrockLLM:
    """Amazon Bedrock chat wrapper.

    A single instance of this class handles both Claude (Anthropic) and
    Amazon Nova models.  It accepts a config dictionary describing the
    underlying model and run‑time parameters.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        llm_conf = config.get("llm", {})
        bed_conf = config.get("bedrock", {})
        model_id = llm_conf.get("model_id")
        if not model_id or "$" in model_id:
            model_id = "amazon.nova-pro-v1:0"

        region = bed_conf.get("region_name")
        if not region or "$" in region:
            region = os.getenv("AWS_REGION", "us-east-1")

        def _safe_cast(value: Any, cast, default):
            try:
                return cast(value)
            except (TypeError, ValueError):
                return default

        temperature = _safe_cast(llm_conf.get("temperature"), float, 0.2)
        top_p = _safe_cast(llm_conf.get("top_p"), float, 0.9)
        max_tokens = _safe_cast(llm_conf.get("max_tokens"), int, 400)
        logger.debug(
            "Initialising BedrockLLM model_id=%s region=%s temperature=%s top_p=%s max_tokens=%s",
            model_id,
            region,
            temperature,
            top_p,
            max_tokens,
        )

        # Create a Bedrock runtime client with adaptive retries
        self._br = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(retries={"max_attempts": 12, "mode": "adaptive"}),
        )

        # Build a common prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an inventory assistant. Be concise and factual. "
                    "Use the provided context to answer the user and say 'I don't know' if unsure.",
                ),
                ("system", "{context}"),
                MessagesPlaceholder("chat_history"),
                ("human", "{user_request}"),
            ]
        )

        # Determine which Bedrock invocation API to use
        if model_id.startswith("anthropic."):
            logger.debug("Using ChatBedrock interface for model %s", model_id)
            # Claude (Anthropic) models use the ChatBedrock interface
            self.client = ChatBedrock(
                model_id=model_id,
                client=self._br,
                model_kwargs={
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                    "anthropic_version": "bedrock-2023-05-31",
                },
            )
        elif model_id.startswith("amazon.nova-"):
            logger.debug("Using converse API for model %s", model_id)
            # Amazon Nova models use the `converse` API wrapped in a Runnable
            def _normalize_to_role_text(x: Any) -> Tuple[str, str]:
                """Normalize various message formats into (role, text)."""
                # LangChain BaseMessage
                if hasattr(x, "type"):
                    role = {
                        "human": "user",
                        "ai": "assistant",
                        "system": "system",
                    }.get(getattr(x, "type"), "user")
                    content = getattr(x, "content", "")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list) and content and isinstance(content[0], dict):
                        text = content[0].get("text", str(content))
                    else:
                        text = str(content)
                    return role, text
                # Tuple (role, text)
                if isinstance(x, tuple) and len(x) == 2:
                    return str(x[0]), str(x[1])
                # Dict {role: ..., content: ...}
                if isinstance(x, dict):
                    role = str(x.get("role", "user"))
                    c = x.get("content", "")
                    if isinstance(c, str):
                        text = c
                    elif isinstance(c, list) and c and isinstance(c[0], dict):
                        text = c[0].get("text", str(c))
                    else:
                        text = str(c)
                    return role, text
                # Plain string
                return "user", str(x)

            def _nova_runnable(messages: List[Any]) -> str:
                # Ensure list
                if not isinstance(messages, (list, tuple)):
                    messages = [messages]
                br_messages = []
                for m in messages:
                    role, text = _normalize_to_role_text(m)
                    br_messages.append({"role": role, "content": [{"text": text}]})
                response = self._br.converse(
                    modelId=model_id,
                    messages=br_messages,
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                        "topP": top_p,
                    },
                )
                return response["output"]["message"]["content"][0]["text"]

            self.client = RunnableLambda(_nova_runnable)
        else:
            logger.error("Unsupported Bedrock model id: %s", model_id)

            raise ValueError(f"Unsupported Bedrock model id: {model_id}")

        # Compose the pipeline: prompt → client → output parser
        self.chain = self.prompt | self.client | StrOutputParser()

    def generate(
        self,
        user_request: str,
        chat_history: List[Tuple[str, str]],
        context: str | None = None,
    ) -> str:
        """Generate a response based on the user request and chat history."""
        logger.info("Generating response via BedrockLLM")
        response = self.chain.invoke(
            {
                "chat_history": chat_history,
                "user_request": user_request,
                "context": context or "",
            }
        )
        logger.debug("BedrockLLM response: %s", response)
        return response
