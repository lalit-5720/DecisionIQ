from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "DecisionIQ API"
    database_url: str = f"sqlite:///{ROOT_DIR / 'decisioniq.db'}"
    data_dir: Path = ROOT_DIR / "data"
    cors_origins: list[str] = ["http://localhost:5173"]
    jwt_secret: str | None = None      # DIQ_JWT_SECRET; otherwise generated into data/.jwt_secret
    token_hours: int = 8
    demo_mode: bool = True             # DIQ_DEMO_MODE=false hides the demo persona hints on the login page

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DIQ_")


settings = Settings()
