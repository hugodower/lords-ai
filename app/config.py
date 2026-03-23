from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Org
    org_id: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Claude API
    claude_api_key: str

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

    # Config
    log_level: str = "INFO"
    max_response_time_seconds: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
