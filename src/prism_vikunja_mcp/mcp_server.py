"""mcp server wiring for vikunja openapi coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp import types
from mcp.server import Server

from prism_vikunja_mcp import __version__
from prism_vikunja_mcp.openapi_registry import VikunjaOpenApiRegistry
from prism_vikunja_mcp.vikunja_api_client import VikunjaApiClient

if TYPE_CHECKING:
    from prism_vikunja_mcp.configuration import VikunjaServerConfiguration

LIST_OPERATIONS_TOOL_NAME = "vikunja_list_operations"
RELOAD_OPENAPI_TOOL_NAME = "vikunja_reload_openapi"


def build_internal_tool_definitions() -> list[types.Tool]:
    """return built-in helper tools for operation discovery and spec refresh."""
    return [
        types.Tool(
            name=LIST_OPERATIONS_TOOL_NAME,
            description="List available Vikunja API operations exposed as MCP tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "optional tag filter, for example task, project, user",
                    },
                    "name_contains": {
                        "type": "string",
                        "description": "optional substring filter for tool name",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "maximum number of operations to return",
                        "minimum": 1,
                        "maximum": 500,
                        "default": 100,
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name=RELOAD_OPENAPI_TOOL_NAME,
            description="Reload the Vikunja OpenAPI document and regenerate all operation tools.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ]


class VikunjaMcpApplication:
    """runtime container for tool definitions and operation execution."""

    def __init__(self, configuration: VikunjaServerConfiguration) -> None:
        self.configuration = configuration
        self.registry: VikunjaOpenApiRegistry | None = None
        self.api_client: VikunjaApiClient | None = None

        self.server = Server(
            name="prism-vikunja-mcp",
            version=__version__,
            instructions=(
                "this server exposes vikunja swagger endpoints as mcp tools. "
                "use vikunja_list_operations to discover operation names, then call the matching tool directly."
            ),
        )

        self.internal_tools = build_internal_tool_definitions()
        self._register_handlers()

    async def initialize(self) -> None:
        """load swagger, build tool registry, and initialize api client."""
        await self.reload_openapi_registry()

    async def close(self) -> None:
        """close active network resources."""
        if self.api_client is not None:
            await self.api_client.close()

    async def reload_openapi_registry(self) -> None:
        """refresh operation registry from the configured swagger endpoint."""
        candidate_client = VikunjaApiClient(
            configuration=self.configuration,
            api_base_path="/api/v1",
        )

        try:
            swagger_document = await candidate_client.fetch_swagger_document()
            candidate_registry = VikunjaOpenApiRegistry.from_swagger_document(swagger_document)
        except Exception:
            await candidate_client.close()
            raise

        previous_client = self.api_client
        self.api_client = candidate_client
        self.registry = candidate_registry

        if previous_client is not None:
            await previous_client.close()

    def _register_handlers(self) -> None:
        """register mcp list-tools and call-tool handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            operation_tools: list[types.Tool] = []
            if self.registry is not None:
                operation_tools = self.registry.to_mcp_tools()

            return [*self.internal_tools, *operation_tools]

        @self.server.call_tool()
        async def call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if tool_name == LIST_OPERATIONS_TOOL_NAME:
                return self._handle_list_operations(arguments)

            if tool_name == RELOAD_OPENAPI_TOOL_NAME:
                await self.reload_openapi_registry()
                return {
                    "reloaded": True,
                    "operation_count": len(self.registry.operations) if self.registry else 0,
                }

            if self.registry is None:
                raise ValueError("operation registry is not initialized")
            if self.api_client is None:
                raise ValueError("api client is not initialized")

            operation = self.registry.get_operation(tool_name)
            if operation is None:
                raise ValueError(f"unknown tool: {tool_name}")

            result = await self.api_client.execute_operation(operation, arguments)
            return {
                "tool": tool_name,
                "method": operation.method,
                "path": operation.path,
                "status_code": result.status_code,
                "reason_phrase": result.reason_phrase,
                "body": result.body,
            }

    def _handle_list_operations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """return filtered operation metadata to help with tool discovery."""
        if self.registry is None:
            raise ValueError("operation registry is not initialized")

        raw_limit = arguments.get("limit", 100)
        limit = int(raw_limit)
        if limit < 1:
            raise ValueError("limit must be greater than or equal to 1")
        if limit > 500:
            raise ValueError("limit must be less than or equal to 500")

        tag_filter = str(arguments.get("tag", "")).strip().lower()
        name_filter = str(arguments.get("name_contains", "")).strip().lower()

        operation_metadata = self.registry.list_operation_metadata()
        filtered_metadata: list[dict[str, Any]] = []
        for item in operation_metadata:
            if tag_filter:
                tag_values = [tag.lower() for tag in item.get("tags", [])]
                if tag_filter not in tag_values:
                    continue

            if name_filter:
                tool_name = str(item.get("tool_name", "")).lower()
                if name_filter not in tool_name:
                    continue

            filtered_metadata.append(item)

        return {
            "total_operations": len(operation_metadata),
            "returned_operations": len(filtered_metadata[:limit]),
            "operations": filtered_metadata[:limit],
        }
