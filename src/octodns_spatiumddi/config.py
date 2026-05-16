from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SpatiumDDIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    token: SecretStr
    group: str
    view: str | None = None
    insecure: bool = False
    timeout: float = Field(default=30.0, gt=0)
    retries: int = Field(default=3, ge=0)
    include_auto_generated: bool = True
    include_pool_members: bool = False

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v.rstrip("/")
