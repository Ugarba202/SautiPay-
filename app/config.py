from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional, Union, Any


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    LND_REST_URL: str = "http://127.0.0.1:8080"
    LND_MACAROON_HEX: str = ""
    LND_TLS_CERT_PATH: str = "./tls.cert"

    AT_USERNAME: str = "sandbox"
    AT_API_KEY: str = ""
    AT_SHORTCODE: str = "*384#"
    AT_SENDER_ID: str = "SAUTIPAY"

    RATE_API_URL: str = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=ngn"
    RATE_OVERRIDE_NGN: Optional[Union[float, str]] = None

    DEMO_MODE: bool = True
    PORT: int = 8000
    DB_PATH: str = "sautipay.db"

    @field_validator("RATE_OVERRIDE_NGN", mode="before")
    @classmethod
    def parse_rate_override(cls, v: Any) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None


settings = Settings()

