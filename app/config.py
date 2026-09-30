from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Storage -- PostgreSQL only, e.g. postgresql://user:pass@host:5432/db (postgres:// URLs are accepted).
    # Required: the app refuses to start without it (see .env.example for Supabase and Docker examples).
    database_url: str | None = None

    # Security: when set, every /api call must send header  X-API-Key: <value>
    api_key: str | None = None
    secret_key: str | None = None                     # encrypts API keys saved from Settings (keep it secret, don't change it)
    session_days: int = 14                            # how long a sign-in lasts
    admin_email: str | None = None                    # first admin, created on startup if there are no users yet
    admin_password: str | None = None
    admin_name: str | None = None
    # "Sign in with Google" (optional): OAuth client from Google Cloud Console -> APIs & Services -> Credentials.
    # Only people already added as admins can get in; everyone else is refused.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    public_url: str | None = None                     # e.g. https://studio.travelepisodes.in (for the Google redirect)
    cron_secret: str | None = None                    # protects /api/cron/daily (Vercel sends it automatically)
    enable_api_docs: bool = False                     # /api/docs (Swagger) -- needs sign-in when enabled
    cors_origins: str | None = None                   # e.g. "https://travelepisodes.in,https://www.travelepisodes.in"

    # Extraction (Claude API)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None                 # only used when that provider is chosen in Settings
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    custom_ai_api_key: str | None = None
    extraction_model: str = "claude-sonnet-5-5"      # cheaper: claude-haiku-4-5-20251001
    extraction_max_tokens: int = 32000
    chunk_chars: int = 60000                          # split very large documents into chunks of ~this size
    pdf_mode: str = "auto"                            # auto | text | native  (native = send the PDF itself to Claude)
    fixtures_dir: Path | None = None                  # use saved extraction JSON instead of the API (demo / tests)

    # Processing: "inline" reads the document during the upload request (needed on Vercel / serverless);
    # "background" returns immediately and reads it afterwards (fine on a normal server)
    process_mode: str = "inline"

    # Business defaults (Travel Episodes is India based)
    default_currency: str = "INR"
    weekend_days: str = "fri,sat"                     # nights that count as "weekend" when a sheet just says weekend
    auto_approve: bool = False                        # load straight to live rates when there are no errors
    max_upload_mb: float = 4.4                        # Vercel's request limit is 4.5 MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
