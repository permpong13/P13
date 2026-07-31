# -*- coding: utf-8 -*-
"""Connect to a running P13 Streamable HTTP server and list its MCP tools."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


async def inspect_streams(stream_context, label: str) -> None:
    async with stream_context as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            print("Connected: {}".format(label))
            print("Tools: {}".format(len(result.tools)))
            for tool in result.tools:
                print("- {}".format(tool.name))


async def inspect_server(url: str, transport: str) -> None:
    if transport == "stdio":
        server = StdioServerParameters(
            command="uv",
            args=["run", "main.py", "--transport", "stdio"],
            cwd=Path(__file__).resolve().parent,
        )
        await inspect_streams(stdio_client(server), "P13 Revit MCP stdio")
    elif transport == "sse":
        await inspect_streams(sse_client(url, headers=get_auth_headers()), url)
    else:
        async with httpx.AsyncClient(headers=get_auth_headers()) as client:
            await inspect_streams(
                streamable_http_client(url, http_client=client),
                url,
            )


def get_auth_headers() -> dict:
    configured_path = os.environ.get("P13_MCP_CONFIG")
    if configured_path:
        config_path = Path(configured_path).expanduser().resolve()
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home())
        config_path = Path(appdata) / "pyRevit" / "P13" / "mcp_config.json"
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    token = str(config.get("mcp_token") or "")
    if not token:
        raise RuntimeError("P13 MCP HTTP token is missing. Reload pyRevit first.")
    return {"Authorization": "Bearer {}".format(token)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8013/mcp",
        help="P13 Streamable HTTP or SSE MCP endpoint.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="streamable-http",
    )
    arguments = parser.parse_args()
    asyncio.run(inspect_server(arguments.url, arguments.transport))


if __name__ == "__main__":
    main()
