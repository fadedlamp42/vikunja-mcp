"""validation helpers for generated mcp tool schemas."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx

from prism_vikunja_mcp.openapi_registry import VikunjaOpenApiRegistry

DEFAULT_OPENAPI_URL = "https://try.vikunja.io/api/v1/docs.json"


@dataclass(frozen=True)
class SchemaValidationIssue:
    """one schema validation problem found in a generated tool."""

    tool_name: str
    path: str
    message: str


def find_array_schemas_missing_items(schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """find all json schema array nodes that omit the items keyword."""
    issues: list[str] = []

    schema_type = schema.get("type")
    if schema_type == "array" and "items" not in schema:
        issues.append(path)

    if "items" in schema and isinstance(schema["items"], dict):
        issues.extend(
            find_array_schemas_missing_items(
                schema["items"],
                path=f"{path}.items",
            )
        )

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for property_name, property_schema in properties.items():
            if isinstance(property_schema, dict):
                issues.extend(
                    find_array_schemas_missing_items(
                        property_schema,
                        path=f"{path}.properties.{property_name}",
                    )
                )

    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        issues.extend(
            find_array_schemas_missing_items(
                additional_properties,
                path=f"{path}.additionalProperties",
            )
        )

    for composite_key in ["allOf", "anyOf", "oneOf"]:
        composite_value = schema.get(composite_key)
        if isinstance(composite_value, list):
            for index, entry in enumerate(composite_value):
                if isinstance(entry, dict):
                    issues.extend(
                        find_array_schemas_missing_items(
                            entry,
                            path=f"{path}.{composite_key}[{index}]",
                        )
                    )

    return issues


def validate_registry_schemas(
    registry: VikunjaOpenApiRegistry,
) -> list[SchemaValidationIssue]:
    """validate every generated tool schema in a registry."""
    issues: list[SchemaValidationIssue] = []

    for operation in registry.operations.values():
        for path in find_array_schemas_missing_items(operation.input_schema):
            issues.append(
                SchemaValidationIssue(
                    tool_name=operation.tool_name,
                    path=path,
                    message="array schema missing items",
                )
            )

    return issues


async def fetch_swagger_document(swagger_url: str) -> dict[str, Any]:
    """download the swagger document for validation."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(swagger_url)
        response.raise_for_status()
        document = response.json()

    if not isinstance(document, dict):
        raise ValueError("swagger document must be a json object")

    if "paths" not in document:
        raise ValueError("swagger document is missing paths")

    return document


async def run_schema_validation(swagger_url: str) -> int:
    """run validation and return process exit code."""
    document = await fetch_swagger_document(swagger_url)
    registry = VikunjaOpenApiRegistry.from_swagger_document(document)
    issues = validate_registry_schemas(registry)

    print(f"validated {len(registry.operations)} operations from {swagger_url}")
    if not issues:
        print("all generated tool schemas passed validation")
        return 0

    print(f"found {len(issues)} schema issues")
    for issue in issues:
        print(f"- {issue.tool_name}: {issue.message} at {issue.path}")

    return 1


def main() -> None:
    """parse cli args and run validation."""
    parser = argparse.ArgumentParser(description="validate generated vikunja mcp tool schemas")
    parser.add_argument(
        "--swagger-url",
        default=os.getenv("VIKUNJA_VALIDATION_OPENAPI_URL", DEFAULT_OPENAPI_URL),
        help="swagger json url to validate",
    )
    parsed_arguments = parser.parse_args()

    raise SystemExit(asyncio.run(run_schema_validation(parsed_arguments.swagger_url)))


if __name__ == "__main__":
    main()
