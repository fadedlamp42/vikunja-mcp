"""swagger parsing and tool registry generation for vikunja."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from mcp import types

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass(frozen=True)
class OperationParameterBinding:
    """maps a tool argument to an http parameter location."""

    argument_name: str
    parameter_name: str
    location: str
    required: bool
    is_file_upload: bool


@dataclass(frozen=True)
class VikunjaOperationDefinition:
    """an executable operation generated from swagger."""

    tool_name: str
    method: str
    path: str
    summary: str
    tags: tuple[str, ...]
    input_schema: dict[str, Any]
    parameter_bindings: tuple[OperationParameterBinding, ...]


def normalize_identifier(raw_value: str) -> str:
    """convert any operation or parameter name into a safe python-ish identifier."""
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_value).strip("_").lower()
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        return "field"
    if normalized[0].isdigit():
        return f"field_{normalized}"
    return normalized


def resolve_schema_references(
    schema: dict[str, Any],
    definitions: dict[str, Any],
    seen_references: set[str] | None = None,
) -> dict[str, Any]:
    """resolve swagger $ref pointers into plain json schema objects."""
    active_references = seen_references or set()

    if "$ref" in schema:
        reference = schema["$ref"]
        if reference in active_references:
            return {
                "type": "object",
                "description": f"recursive schema omitted for {reference}",
            }

        if not reference.startswith("#/definitions/"):
            return {
                "type": "object",
                "description": f"unsupported schema reference: {reference}",
            }

        definition_name = reference.split("/", maxsplit=2)[-1]
        definition_schema = definitions.get(definition_name, {})
        next_seen_references = set(active_references)
        next_seen_references.add(reference)
        return resolve_schema_references(definition_schema, definitions, next_seen_references)

    resolved_schema = copy.deepcopy(schema)

    if "allOf" in resolved_schema:
        merged_schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        for all_of_entry in resolved_schema["allOf"]:
            resolved_entry = resolve_schema_references(
                all_of_entry, definitions, active_references
            )
            if resolved_entry.get("properties"):
                merged_schema.setdefault("properties", {}).update(resolved_entry["properties"])
            if resolved_entry.get("required"):
                merged_schema.setdefault("required", []).extend(resolved_entry["required"])

            for scalar_key in ["type", "description", "format", "enum", "items"]:
                if scalar_key in resolved_entry and scalar_key not in merged_schema:
                    merged_schema[scalar_key] = resolved_entry[scalar_key]

        merged_schema["required"] = sorted(set(merged_schema.get("required", [])))
        return merged_schema

    if "oneOf" in resolved_schema:
        resolved_schema["oneOf"] = [
            resolve_schema_references(entry, definitions, active_references)
            for entry in resolved_schema["oneOf"]
        ]

    if "anyOf" in resolved_schema:
        resolved_schema["anyOf"] = [
            resolve_schema_references(entry, definitions, active_references)
            for entry in resolved_schema["anyOf"]
        ]

    if "items" in resolved_schema and isinstance(resolved_schema["items"], dict):
        resolved_schema["items"] = resolve_schema_references(
            resolved_schema["items"], definitions, active_references
        )

    if "properties" in resolved_schema and isinstance(resolved_schema["properties"], dict):
        resolved_schema["properties"] = {
            property_name: resolve_schema_references(
                property_schema, definitions, active_references
            )
            if isinstance(property_schema, dict)
            else property_schema
            for property_name, property_schema in resolved_schema["properties"].items()
        }

    additional_properties = resolved_schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        resolved_schema["additionalProperties"] = resolve_schema_references(
            additional_properties,
            definitions,
            active_references,
        )

    return resolved_schema


def ensure_array_items_in_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """ensure every array schema includes an items definition."""
    normalized_schema = copy.deepcopy(schema)

    schema_type = normalized_schema.get("type")
    if schema_type == "array" and "items" not in normalized_schema:
        normalized_schema["items"] = {"type": "string"}

    if "items" in normalized_schema and isinstance(normalized_schema["items"], dict):
        normalized_schema["items"] = ensure_array_items_in_schema(normalized_schema["items"])

    if "properties" in normalized_schema and isinstance(normalized_schema["properties"], dict):
        normalized_schema["properties"] = {
            property_name: ensure_array_items_in_schema(property_schema)
            if isinstance(property_schema, dict)
            else property_schema
            for property_name, property_schema in normalized_schema["properties"].items()
        }

    if "additionalProperties" in normalized_schema and isinstance(
        normalized_schema["additionalProperties"],
        dict,
    ):
        normalized_schema["additionalProperties"] = ensure_array_items_in_schema(
            normalized_schema["additionalProperties"]
        )

    for composite_key in ["allOf", "anyOf", "oneOf"]:
        if composite_key in normalized_schema and isinstance(
            normalized_schema[composite_key], list
        ):
            normalized_schema[composite_key] = [
                ensure_array_items_in_schema(entry) if isinstance(entry, dict) else entry
                for entry in normalized_schema[composite_key]
            ]

    return normalized_schema


def resolve_parameter_reference(
    parameter: dict[str, Any], definitions: dict[str, Any]
) -> dict[str, Any]:
    """resolve a parameter object, including shared parameter references."""
    if "$ref" not in parameter:
        return parameter

    reference = parameter["$ref"]
    if reference.startswith("#/parameters/"):
        parameter_name = reference.split("/", maxsplit=2)[-1]
        shared_parameters = definitions.get("__parameters__", {})
        return copy.deepcopy(shared_parameters.get(parameter_name, {}))

    return copy.deepcopy(parameter)


def build_tool_name(
    operation_id: str | None, method: str, path: str, existing_names: set[str]
) -> str:
    """build a unique tool name for a swagger operation."""
    if operation_id:
        base_name = normalize_identifier(operation_id)
    else:
        base_name = normalize_identifier(f"{method}_{path.replace('/', '_')}")

    if base_name not in existing_names:
        existing_names.add(base_name)
        return base_name

    suffix = 2
    candidate_name = f"{base_name}_{suffix}"
    while candidate_name in existing_names:
        suffix += 1
        candidate_name = f"{base_name}_{suffix}"

    existing_names.add(candidate_name)
    return candidate_name


def convert_non_body_parameter_schema(
    parameter: dict[str, Any], definitions: dict[str, Any]
) -> dict[str, Any]:
    """convert swagger non-body parameters into json schema."""
    if "schema" in parameter and isinstance(parameter["schema"], dict):
        return resolve_schema_references(parameter["schema"], definitions)

    schema: dict[str, Any] = {"type": parameter.get("type", "string")}
    for optional_key in [
        "format",
        "enum",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "description",
    ]:
        if optional_key in parameter:
            schema[optional_key] = parameter[optional_key]

    if "items" in parameter and isinstance(parameter["items"], dict):
        schema["items"] = resolve_schema_references(parameter["items"], definitions)

    return schema


class VikunjaOpenApiRegistry:
    """stores generated mcp tools and operation metadata from vikunja swagger."""

    def __init__(
        self, *, base_path: str, operations: dict[str, VikunjaOperationDefinition]
    ) -> None:
        self.base_path = base_path.rstrip("/") or "/api/v1"
        self.operations = operations

    @classmethod
    def from_swagger_document(cls, swagger_document: dict[str, Any]) -> VikunjaOpenApiRegistry:
        """build an operation registry from a swagger 2.0 document."""
        definitions = copy.deepcopy(swagger_document.get("definitions", {}))
        definitions["__parameters__"] = copy.deepcopy(swagger_document.get("parameters", {}))

        base_path = swagger_document.get("basePath") or "/api/v1"
        paths = swagger_document.get("paths", {})

        operations: dict[str, VikunjaOperationDefinition] = {}
        reserved_tool_names: set[str] = set()

        for path, path_item in paths.items():
            path_level_parameters = path_item.get("parameters", [])

            for method, operation_data in path_item.items():
                if method.lower() not in HTTP_METHODS:
                    continue

                operation_parameters = operation_data.get("parameters", [])
                combined_parameters = [*path_level_parameters, *operation_parameters]

                unique_parameters_by_location: dict[tuple[str, str], dict[str, Any]] = {}
                for parameter in combined_parameters:
                    resolved_parameter = resolve_parameter_reference(parameter, definitions)
                    if not resolved_parameter:
                        continue

                    parameter_name = resolved_parameter.get("name")
                    parameter_location = resolved_parameter.get("in")
                    if not parameter_name or not parameter_location:
                        continue

                    unique_parameters_by_location[(parameter_name, parameter_location)] = (
                        resolved_parameter
                    )

                input_schema: dict[str, Any] = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                }
                parameter_bindings: list[OperationParameterBinding] = []

                for parameter in unique_parameters_by_location.values():
                    parameter_name = parameter["name"]
                    parameter_location = parameter["in"]
                    required = bool(parameter.get("required", False))

                    argument_name_seed = normalize_identifier(parameter_name)
                    argument_name = argument_name_seed
                    if argument_name in input_schema["properties"]:
                        argument_name = (
                            f"{argument_name}_{normalize_identifier(parameter_location)}"
                        )

                    if argument_name in input_schema["properties"]:
                        suffix = 2
                        candidate_name = f"{argument_name}_{suffix}"
                        while candidate_name in input_schema["properties"]:
                            suffix += 1
                            candidate_name = f"{argument_name}_{suffix}"
                        argument_name = candidate_name

                    if parameter_location == "body":
                        body_schema = parameter.get("schema", {"type": "object"})
                        parameter_schema = resolve_schema_references(body_schema, definitions)
                    elif parameter_location == "formData" and parameter.get("type") == "file":
                        parameter_schema = {
                            "type": "string",
                            "description": "absolute path to local file for multipart upload",
                        }
                    else:
                        parameter_schema = convert_non_body_parameter_schema(
                            parameter, definitions
                        )

                    parameter_schema = ensure_array_items_in_schema(parameter_schema)

                    description_suffix = f"location: {parameter_location}"
                    existing_description = parameter_schema.get("description", "")
                    if existing_description:
                        parameter_schema["description"] = (
                            f"{existing_description} ({description_suffix})"
                        )
                    else:
                        parameter_schema["description"] = description_suffix

                    input_schema["properties"][argument_name] = parameter_schema
                    if required:
                        input_schema["required"].append(argument_name)

                    parameter_bindings.append(
                        OperationParameterBinding(
                            argument_name=argument_name,
                            parameter_name=parameter_name,
                            location=parameter_location,
                            required=required,
                            is_file_upload=parameter_location == "formData"
                            and parameter.get("type") == "file",
                        )
                    )

                if not input_schema["required"]:
                    input_schema.pop("required")

                generated_tool_name = build_tool_name(
                    operation_data.get("operationId"),
                    method,
                    path,
                    reserved_tool_names,
                )

                summary = operation_data.get("summary") or operation_data.get("description") or ""
                description_lines = [
                    summary.strip(),
                    f"{method.upper()} {path}",
                ]
                tags = tuple(operation_data.get("tags", []))
                if tags:
                    description_lines.append(f"tags: {', '.join(tags)}")

                operation_definition = VikunjaOperationDefinition(
                    tool_name=generated_tool_name,
                    method=method.upper(),
                    path=path,
                    summary="\n".join([line for line in description_lines if line]),
                    tags=tags,
                    input_schema=input_schema,
                    parameter_bindings=tuple(parameter_bindings),
                )
                operations[generated_tool_name] = operation_definition

        return cls(base_path=base_path, operations=operations)

    def to_mcp_tools(self) -> list[types.Tool]:
        """convert all operations into mcp tool definitions."""
        tool_definitions: list[types.Tool] = []
        for operation in self.operations.values():
            tool_definitions.append(
                types.Tool(
                    name=operation.tool_name,
                    description=operation.summary,
                    inputSchema=operation.input_schema,
                )
            )

        return tool_definitions

    def get_operation(self, tool_name: str) -> VikunjaOperationDefinition | None:
        """return an operation by tool name."""
        return self.operations.get(tool_name)

    def list_operation_metadata(self) -> list[dict[str, Any]]:
        """list lightweight metadata for operation discovery."""
        metadata: list[dict[str, Any]] = []
        for operation in self.operations.values():
            metadata.append(
                {
                    "tool_name": operation.tool_name,
                    "method": operation.method,
                    "path": operation.path,
                    "tags": list(operation.tags),
                    "argument_names": [
                        binding.argument_name for binding in operation.parameter_bindings
                    ],
                }
            )

        return metadata
