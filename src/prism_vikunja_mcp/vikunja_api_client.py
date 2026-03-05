"""http client wrapper around the vikunja api."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from prism_vikunja_mcp.configuration import VikunjaServerConfiguration
    from prism_vikunja_mcp.openapi_registry import VikunjaOperationDefinition


@dataclass(frozen=True)
class VikunjaApiExecutionResult:
    """normalized response returned by an api operation call."""

    status_code: int
    reason_phrase: str
    headers: dict[str, str]
    body: Any


def split_vikunja_root_and_api_prefix(api_base: str, api_prefix: str) -> tuple[str, str]:
    """normalize api base values whether or not /api/v1 is already present."""
    normalized_api_prefix = api_prefix.rstrip("/")
    normalized_api_base = api_base.rstrip("/")

    if normalized_api_prefix and normalized_api_base.endswith(normalized_api_prefix):
        root_url = normalized_api_base[: -len(normalized_api_prefix)]
        root_url = root_url.rstrip("/")
    else:
        root_url = normalized_api_base

    if not root_url:
        root_url = normalized_api_base

    return root_url, normalized_api_prefix


def convert_form_value(value: Any) -> str:
    """convert non-file values into safe multipart/form field strings."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value)


class VikunjaApiClient:
    """handles authenticated requests against vikunja endpoints."""

    def __init__(
        self,
        *,
        configuration: VikunjaServerConfiguration,
        api_base_path: str,
    ) -> None:
        self.configuration = configuration
        self.api_base_path = api_base_path.rstrip("/")

        root_url, api_prefix = split_vikunja_root_and_api_prefix(
            configuration.vikunja_api_base,
            self.api_base_path,
        )

        verify_setting: bool | str
        if configuration.tls_ca_bundle_path:
            verify_setting = configuration.tls_ca_bundle_path
        else:
            verify_setting = configuration.verify_tls

        base_url = f"{root_url}{api_prefix}"
        self.http_client = httpx.AsyncClient(
            base_url=base_url,
            timeout=configuration.request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {configuration.vikunja_api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            verify=verify_setting,
        )

    async def close(self) -> None:
        """close the underlying http client."""
        await self.http_client.aclose()

    async def fetch_swagger_document(self) -> dict[str, Any]:
        """download the swagger document from the configured vikunja instance."""
        response = await self.http_client.get(
            self.configuration.vikunja_openapi_url,
            headers={"Authorization": f"Bearer {self.configuration.vikunja_api_token}"},
        )
        response.raise_for_status()

        document = response.json()
        if not isinstance(document, dict):
            raise ValueError("openapi document must be a json object")

        if "paths" not in document:
            raise ValueError("openapi document is missing paths")

        return document

    async def execute_operation(
        self,
        operation: VikunjaOperationDefinition,
        arguments: dict[str, Any],
    ) -> VikunjaApiExecutionResult:
        """execute an operation with mcp-provided arguments."""
        resolved_path = operation.path
        query_parameters: dict[str, Any] = {}
        extra_headers: dict[str, str] = {}
        json_body: Any = None
        form_values: dict[str, str] = {}
        files: dict[str, tuple[str, bytes, str]] = {}

        for binding in operation.parameter_bindings:
            value_present = binding.argument_name in arguments
            value = arguments.get(binding.argument_name)

            if not value_present:
                if binding.required:
                    raise ValueError(f"missing required argument: {binding.argument_name}")
                continue

            if binding.location == "path":
                encoded_value = quote(str(value), safe="")
                resolved_path = resolved_path.replace(
                    f"{{{binding.parameter_name}}}", encoded_value
                )
                continue

            if binding.location == "query":
                query_parameters[binding.parameter_name] = value
                continue

            if binding.location == "header":
                extra_headers[binding.parameter_name] = str(value)
                continue

            if binding.location == "body":
                json_body = value
                continue

            if binding.location == "formData":
                if binding.is_file_upload:
                    uploaded_file_path = Path(str(value)).expanduser().resolve()
                    if not uploaded_file_path.exists():
                        raise ValueError(f"file does not exist: {uploaded_file_path}")
                    if not uploaded_file_path.is_file():
                        raise ValueError(f"path is not a file: {uploaded_file_path}")

                    file_bytes = uploaded_file_path.read_bytes()
                    files[binding.parameter_name] = (
                        uploaded_file_path.name,
                        file_bytes,
                        "application/octet-stream",
                    )
                else:
                    form_values[binding.parameter_name] = convert_form_value(value)
                continue

            raise ValueError(f"unsupported parameter location: {binding.location}")

        request_kwargs: dict[str, Any] = {
            "params": query_parameters or None,
            "headers": extra_headers or None,
        }

        if files or form_values:
            request_kwargs["data"] = form_values or None
            request_kwargs["files"] = files or None
            request_kwargs["headers"] = {
                **(extra_headers or {}),
                "Authorization": f"Bearer {self.configuration.vikunja_api_token}",
                "Accept": "application/json",
            }
        else:
            request_kwargs["json"] = json_body

        response = await self.http_client.request(
            method=operation.method,
            url=resolved_path.lstrip("/"),
            **request_kwargs,
        )

        if response.status_code >= 400:
            response_message = response.text.strip()
            if response_message:
                raise ValueError(
                    f"{response.status_code} {response.reason_phrase}: {response_message}"
                )
            raise ValueError(f"{response.status_code} {response.reason_phrase}")

        response_content_type = response.headers.get("content-type", "").lower()
        if "application/json" in response_content_type:
            parsed_body: Any = response.json()
        else:
            parsed_body = response.text

        return VikunjaApiExecutionResult(
            status_code=response.status_code,
            reason_phrase=response.reason_phrase,
            headers=dict(response.headers),
            body=parsed_body,
        )
