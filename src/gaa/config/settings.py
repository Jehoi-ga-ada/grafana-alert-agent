"""Application settings loaded from environment / .env (schema-validated)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Secrets come from env / .env only."""

    model_config = SettingsConfigDict(
        env_prefix="GAA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # Grafana
    grafana_url: str = "https://grafana10.private.devopsinstitute.id"
    grafana_sa_token: str = ""
    grafana_ca_cert: str = ""
    tls_insecure: bool = False

    # Discord
    discord_webhook_url: str = ""  # one-way alert delivery
    discord_bot_token: str = ""  # two-way chat bot (gateway)
    discord_channel_id: int = 0  # optional: only respond in this channel (0 = anywhere)

    # LLM provider: "bedrock" (bearer key) or "anthropic" (direct API)
    llm_provider: str = "bedrock"
    # Chat/agent model provider (LangChain): "bedrock" or "anthropic"
    chat_provider: str = "bedrock"
    # Bound the agent loop so it can't consume tokens unboundedly.
    agent_max_steps: int = 16  # LangGraph recursion limit (≈ max_steps/2 tool rounds)
    agent_max_tokens: int = 1536  # max output tokens per model call
    # Path to the mcp-grafana binary (read-only Grafana MCP server for the chat agent)
    mcp_grafana_bin: str = "mcp-grafana"
    # Allow Grafana Sift analysis tools (find_slow_requests / find_error_pattern_logs).
    # These create a Sift *investigation* (an analysis artifact — no infra change).
    allow_sift: bool = True

    # Anomaly detection + scheduled tasks
    anomalies_path: str = "config/anomalies.yaml"
    sweep_interval_seconds: int = 900  # proactive anomaly sweep cadence
    digest_interval_seconds: int = 0  # 0 = daily digest disabled
    # Bedrock (InvokeModel with a bearer API key)
    bedrock_region: str = "ap-southeast-3"
    bedrock_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_api_key: str = ""
    # Direct Anthropic API (used when llm_provider == "anthropic")
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # Dashboard / screenshots
    dashboard_uid: str = ""
    dashboard_slug: str = "url-shortener-public"

    # LangSmith tracing (LangChain/LangGraph). Off by default; the API key is a
    # secret and must come from .env only — never committed. When enabled, these
    # are exported to the native LANGSMITH_* env vars (see gaa.observability).
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "grafana-agent"

    # Behaviour
    poll_interval_seconds: int = Field(default=30, ge=5)
    default_env: str = "prod"
    rules_path: str = "config/rules.yaml"
    state_db: str = ".gaa/state.db"
    log_level: str = "INFO"

    @field_validator("grafana_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def ca_cert_path(self) -> Path | None:
        if not self.grafana_ca_cert:
            return None
        return Path(self.grafana_ca_cert).expanduser()

    @property
    def state_db_path(self) -> Path:
        return Path(self.state_db).expanduser()

    @property
    def verify(self) -> str | bool:
        """The value httpx/ssl expects for verification."""
        if self.tls_insecure:
            return False
        if self.ca_cert_path is not None:
            return str(self.ca_cert_path)
        return True

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "bedrock":
            return bool(self.bedrock_api_key)
        return bool(self.anthropic_api_key)

    def require(self, *fields: str) -> None:
        """Fail fast if required secret fields are empty."""
        missing = [f for f in fields if not getattr(self, f, "")]
        if missing:
            raise ValueError(
                "missing required settings: "
                + ", ".join(f"GAA_{f.upper()}" for f in missing)
            )
