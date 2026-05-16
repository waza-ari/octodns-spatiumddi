import pytest
from pydantic import ValidationError

from octodns_spatiumddi.config import SpatiumDDIConfig


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "url": "https://spatium.example.com",
        "token": "secret",
        "group": "default",
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_minimal() -> None:
    c = SpatiumDDIConfig(**_base_kwargs())
    assert c.url == "https://spatium.example.com"
    assert c.token.get_secret_value() == "secret"
    assert c.group == "default"
    assert c.view is None
    assert c.insecure is False
    assert c.timeout == 30.0
    assert c.retries == 3
    assert c.include_auto_generated is True
    assert c.include_pool_members is False


def test_url_strips_trailing_slash() -> None:
    c = SpatiumDDIConfig(**_base_kwargs(url="https://x.example.com/"))
    assert c.url == "https://x.example.com"


def test_url_must_be_http_or_https() -> None:
    with pytest.raises(ValidationError):
        SpatiumDDIConfig(**_base_kwargs(url="ftp://x.example.com"))


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        SpatiumDDIConfig(**_base_kwargs(typo="oops"))


def test_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        SpatiumDDIConfig(url="https://x", token="t")  # type: ignore[call-arg]


def test_token_is_secret() -> None:
    c = SpatiumDDIConfig(**_base_kwargs(token="hunter2"))
    assert "hunter2" not in repr(c)


def test_negative_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        SpatiumDDIConfig(**_base_kwargs(timeout=0))
