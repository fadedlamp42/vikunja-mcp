"""configuration loading for the vikunja mcp server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def parse_boolean_environment_value(raw_value: str | None, *, default: bool) -> bool:
    """convert common environment variable booleans into python booleans."""
    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"invalid boolean value: {raw_value!r}")


def parse_float_environment_value(raw_value: str | None, *, default: float) -> float:
    """convert an environment variable into a positive float."""
    if raw_value is None:
        return default

    parsed_value = float(raw_value)
    if parsed_value <= 0:
        raise ValueError("timeout must be greater than zero")

    return parsed_value


def validate_http_url(value: str, *, variable_name: str) -> str:
    """validate that a value is a well-formed http or https url."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{variable_name} must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError(f"{variable_name} is missing a host")

    return value.rstrip("/")


@dataclass(frozen=True)
class VikunjaServerConfiguration:
    """all runtime configuration for the vikunja mcp server."""

    vikunja_api_base: str
    vikunja_api_token: str
    vikunja_openapi_url: str
    verify_tls: bool
    tls_ca_bundle_path: str | None
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> VikunjaServerConfiguration:
        """build configuration from process environment variables."""
        api_base = os.getenv("VIKUNJA_API_BASE")
        api_token = os.getenv("VIKUNJA_API_TOKEN")

        if not api_base:
            raise ValueError("VIKUNJA_API_BASE is required")
        if not api_token:
            raise ValueError("VIKUNJA_API_TOKEN is required")

        validated_api_base = validate_http_url(api_base, variable_name="VIKUNJA_API_BASE")

        raw_openapi_url = os.getenv("VIKUNJA_OPENAPI_URL")
        if raw_openapi_url:
            validated_openapi_url = validate_http_url(
                raw_openapi_url, variable_name="VIKUNJA_OPENAPI_URL"
            )
        else:
            if validated_api_base.endswith("/api/v1"):
                validated_openapi_url = f"{validated_api_base}/docs.json"
            else:
                validated_openapi_url = f"{validated_api_base}/api/v1/docs.json"

        verify_tls = parse_boolean_environment_value(os.getenv("VIKUNJA_VERIFY_TLS"), default=True)
        tls_ca_bundle_path = os.getenv("VIKUNJA_CA_BUNDLE")
        request_timeout_seconds = parse_float_environment_value(
            os.getenv("VIKUNJA_REQUEST_TIMEOUT_SECONDS"),
            default=30.0,
        )

        return cls(
            vikunja_api_base=validated_api_base,
            vikunja_api_token=api_token,
            vikunja_openapi_url=validated_openapi_url,
            verify_tls=verify_tls,
            tls_ca_bundle_path=tls_ca_bundle_path,
            request_timeout_seconds=request_timeout_seconds,
        )
