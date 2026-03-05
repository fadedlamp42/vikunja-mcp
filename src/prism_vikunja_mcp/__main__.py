"""entrypoint for the prism vikunja mcp server."""

from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server import NotificationOptions
from mcp.server.stdio import stdio_server

from prism_vikunja_mcp.configuration import VikunjaServerConfiguration
from prism_vikunja_mcp.mcp_server import VikunjaMcpApplication

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("prism_vikunja_mcp")


async def run_server() -> None:
    """load configuration and run the stdio mcp server."""
    configuration = VikunjaServerConfiguration.from_environment()
    application = VikunjaMcpApplication(configuration)

    await application.initialize()
    logger.info(
        "loaded %s operations from %s",
        len(application.registry.operations) if application.registry else 0,
        configuration.vikunja_openapi_url,
    )

    try:
        async with stdio_server() as (read_stream, write_stream):
            initialization_options = application.server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=True),
            )
            await application.server.run(read_stream, write_stream, initialization_options)
    finally:
        await application.close()


def main() -> None:
    """run the async server entrypoint with clean error handling."""
    try:
        asyncio.run(run_server())
    except Exception as error:
        logger.error("server startup failed: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
