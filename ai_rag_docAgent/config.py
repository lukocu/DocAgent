from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from pathlib import Path

class Settings(BaseSettings):

    openai_api_key: SecretStr = Field(..., alias="OPENAI_API_KEY")
    
    qdrant_url: str = Field("http://localhost:6333", alias="QDRANT_URL")
    meili_url: str = Field("http://localhost:7700", alias="MEILI_URL")
    meili_master_key: SecretStr = Field(..., alias="MEILI_MASTER_KEY")
    postgres_url: str = Field(..., alias="POSTGRES_URL")
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

settings = Settings()