from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr

class Settings(BaseSettings):

    openai_api_key: SecretStr = Field(..., alias="OPENAI_API_KEY")
    
    qdrant_url: str = Field("http://localhost:6333", alias="QDRANT_URL")
    meili_url: str = Field("http://localhost:7700", alias="MEILI_URL")
    meili_master_key: SecretStr = Field(..., alias="MEILI_MASTER_KEY")
    postgres_url: str = Field(..., env="POSTGRES_URL") 
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()