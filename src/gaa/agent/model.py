"""Build the LangChain chat model from settings.

Bedrock uses a bearer API key via ``bedrock_api_key`` (sets AWS_BEARER_TOKEN_BEDROCK
internally) — no IAM credentials required. The model talks to the Bedrock Converse API.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def model_configured(settings) -> bool:
    if settings.chat_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return bool(settings.bedrock_api_key)


def build_chat_model(settings):  # pragma: no cover - provider construction
    """Return a LangChain chat model (BaseChatModel) for the configured provider."""
    if settings.chat_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.claude_model, api_key=settings.anthropic_api_key)

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        bedrock_api_key=settings.bedrock_api_key,
        max_tokens=settings.agent_max_tokens,
    )
