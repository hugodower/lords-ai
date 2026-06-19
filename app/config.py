from pydantic_settings import BaseSettings
import logging

logger = logging.getLogger("config")


class Settings(BaseSettings):
    # Org
    org_id: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Claude API
    claude_api_key: str

    # Modelos Claude — atualizar aqui quando houver deprecation
    claude_model_agent: str = "claude-sonnet-4-6"
    claude_model_intent: str = "claude-haiku-4-5-20251001"

    # Params da geração do agente — defaults globais (override per-org via
    # agent_configs.model_temperature / .model_max_tokens; ver providers/factory.py).
    # Fonte única dos valores que antes eram literais em agents/base.py.
    claude_temperature_agent: float = 0.3
    claude_max_tokens_agent: int = 500

    # Chatwoot
    chatwoot_url: str
    chatwoot_api_token: str
    chatwoot_account_id: int = 1
    chatwoot_bot_agent_id: int = 0  # Chatwoot agent_bot ID to detect self-messages

    # Redis
    redis_url: str = "redis://localhost:6379"

    # ChromaDB
    chroma_url: str = "http://localhost:8000"

    # Google Calendar
    google_client_id: str = ""
    google_client_secret: str = ""

    # Sandbox (DEPRECATED: use agent_configs.sandbox_mode and .sandbox_phones instead)
    # TODO: Remove after migration to DB-only config (per-org in super admin panel)
    sandbox_mode: bool = True
    sandbox_phones: str = "+5518996597391"  # comma-separated allowed phones

    # Config
    log_level: str = "INFO"

    # Follow-up Worker
    followup_worker_enabled: bool = True  # Set to False to disable follow-up worker

    # Legacy field from agent_configs table (currently unused by backend)
    max_response_time_seconds: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
