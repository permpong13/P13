# -*- coding: utf-8 -*-
"""Standalone FastMCP bridge for the secured P13 pyRevit Routes API."""

import argparse
import hmac
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from starlette.responses import JSONResponse


CONFIG_ENVIRONMENT_VARIABLE = "P13_MCP_CONFIG"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8013
MCP_SCOPE = "p13:revit"
HOST_WRITE_POLICY_ENVIRONMENT_VARIABLE = "P13_MCP_HOST_WRITE_POLICY"


def get_config_path() -> Path:
    configured_path = os.environ.get(CONFIG_ENVIRONMENT_VARIABLE)
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    appdata_path = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata_path) / "pyRevit" / "P13" / "mcp_config.json"


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=2, sort_keys=True)
    try:
        os.chmod(temporary_path, stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass
    os.replace(temporary_path, path)


def load_config() -> dict:
    config_path = get_config_path()
    config = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    changed = False
    defaults = {
        "config_version": 3,
        "token": secrets.token_hex(32),
        "mcp_token": secrets.token_hex(32),
        "routes_url": "http://127.0.0.1:48884/p13_mcp",
        "mcp_http_host": DEFAULT_HTTP_HOST,
        "mcp_http_port": DEFAULT_HTTP_PORT,
        "network_policy": "loopback_only",
        "share_document_title": False,
        "share_document_path": False,
        "store_ai_history": False,
        "redact_diagnostics": True,
    }
    for key, default_value in defaults.items():
        if not config.get(key):
            config[key] = default_value
            changed = True
    if config.get("config_version") != 3:
        config["config_version"] = 3
        changed = True
    if config.get("mcp_http_host") not in ("127.0.0.1", "localhost", "::1"):
        config["mcp_http_host"] = DEFAULT_HTTP_HOST
        changed = True
    if changed or not config_path.is_file():
        write_private_json(config_path, config)
    return config


class LocalBearerTokenVerifier:
    """Validate the per-user HTTP bearer token without exposing Routes auth."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        expected_token = str(load_config().get("mcp_token") or "")
        if not expected_token or not hmac.compare_digest(str(token), expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="p13-local-client",
            scopes=[MCP_SCOPE],
            subject="current-windows-user",
        )


def route_url(config: dict, endpoint: str) -> str:
    base_url = str(config.get("routes_url") or "").rstrip("/")
    return "{}/{}/".format(base_url, endpoint.strip("/"))


def parse_route_response(response: httpx.Response) -> dict:
    """Preserve the actionable Revit error instead of exposing only HTTP 400."""
    try:
        data = response.json()
    except Exception:
        data = None
    if response.is_error:
        message = ""
        if isinstance(data, dict):
            message = str(data.get("error") or data.get("message") or "")
        if not message:
            message = "P13 Revit route returned HTTP {}.".format(response.status_code)
        raise RuntimeError(message)
    if not isinstance(data, dict):
        raise RuntimeError("P13 Revit route returned an invalid JSON response.")
    return data


async def get_route(endpoint: str) -> dict:
    config = load_config()
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(route_url(config, endpoint))
        return parse_route_response(response)


async def post_route(endpoint: str, payload: dict) -> dict:
    config = load_config()
    request_payload = dict(payload)
    request_payload["token"] = config["token"]
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            route_url(config, endpoint),
            json=request_payload,
        )
        return parse_route_response(response)


def host_write_blocked(confirm_write: bool) -> Optional[dict]:
    policy = str(
        os.environ.get(HOST_WRITE_POLICY_ENVIRONMENT_VARIABLE) or "allow"
    ).strip().lower()
    if policy == "deny" and bool(confirm_write):
        return {
            "status": "blocked",
            "reason": (
                "The P13 AI Console started this task in read-only mode. "
                "Start a new task and explicitly enable Revit changes."
            ),
        }
    return None


_startup_config = load_config()
_configured_port = int(_startup_config.get("mcp_http_port") or DEFAULT_HTTP_PORT)
_resource_base_url = "http://127.0.0.1:{}".format(_configured_port)


mcp = FastMCP(
    "P13 Revit MCP",
    instructions=(
        "Provider-neutral Revit 2026 tools backed by secured P13 pyRevit Routes. "
        "Read tools are safe by default. Model-writing tools require an explicit "
        "confirm_write=true argument."
    ),
    host=DEFAULT_HTTP_HOST,
    port=_configured_port,
    token_verifier=LocalBearerTokenVerifier(),
    auth=AuthSettings(
        issuer_url=_resource_base_url,
        resource_server_url="{}/mcp".format(_resource_base_url),
        required_scopes=[MCP_SCOPE],
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ],
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Browser-friendly health check without exposing the private Routes token."""
    config = load_config()
    revit_status_url = route_url(config, "status")
    revit_routes = {
        "status": "unavailable",
        "url": revit_status_url,
    }
    try:
        timeout = httpx.Timeout(3.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(revit_status_url)
            response.raise_for_status()
            revit_routes = {
                "status": "active",
            }
    except Exception as error:
        revit_routes["error"] = str(error)

    return JSONResponse(
        {
            "status": "active",
            "server": "P13 Revit MCP",
            "mcp_endpoint": "/mcp",
            "revit_routes": revit_routes,
        }
    )


@mcp.custom_route("/", methods=["GET"])
async def server_information(request):
    """Browser-friendly server information."""
    return JSONResponse(
        {
            "name": "P13 Revit MCP",
            "status": "active",
            "health": "/health",
            "streamable_http": "/mcp",
            "authentication": "Bearer token required for HTTP MCP clients.",
            "note": "Use an MCP client for /mcp; browsers should open /health.",
        }
    )


@mcp.tool()
async def get_p13_revit_status() -> dict:
    """Check whether P13 pyRevit Routes and an active Revit document respond."""
    return await get_route("status")


@mcp.tool()
async def get_p13_document_info() -> dict:
    """Read safe metadata for the active Revit document."""
    return await post_route("document_info", {})


@mcp.tool()
async def get_p13_active_view() -> dict:
    """Read the active Revit view name, type, scale, crop, and detail level."""
    return await post_route("active_view", {})


@mcp.tool()
async def get_p13_selected_elements(limit: int = 500) -> dict:
    """Return metadata for elements currently selected by the Revit user."""
    return await post_route("selected_elements", {"limit": limit})


@mcp.tool()
async def manage_p13_grid_bubbles(
    element_ids: List[int],
    action: str,
    orient_by_view: bool = True,
    confirm_write: bool = False,
) -> dict:
    """Manage bubbles for specified grid IDs in the active view.

    action must be one of: both, none, primary, secondary, smart, toggle.
    primary means left/bottom and secondary means right/top when
    orient_by_view is true. This modifies the model and requires
    confirm_write=true.
    """
    blocked = host_write_blocked(confirm_write)
    if blocked:
        return blocked
    return await post_route(
        "grid_bubbles",
        {
            "element_ids": element_ids,
            "action": action,
            "orient_by_view": orient_by_view,
            "confirm_write": confirm_write,
        },
    )


@mcp.tool()
async def get_p13_model_summary(limit: int = 100000) -> dict:
    """Count model elements by category without modifying the Revit document."""
    return await post_route("model_summary", {"limit": limit})


@mcp.tool()
async def get_p13_levels() -> dict:
    """List levels and their elevations in the active Revit document."""
    return await post_route("levels", {})


@mcp.tool()
async def get_p13_views(include_templates: bool = False) -> dict:
    """List project views, optionally including view templates."""
    return await post_route("views", {"include_templates": include_templates})


@mcp.tool()
async def get_p13_active_view_elements(
    category: str = "",
    limit: int = 1000,
) -> dict:
    """Read elements visible in the active view, optionally filtered by category name."""
    return await post_route(
        "active_view_elements",
        {"category": category, "limit": limit},
    )


@mcp.tool()
async def get_p13_element_parameters(element_id: int) -> dict:
    """Read instance parameters and type identity for one Revit element."""
    return await post_route("element_parameters", {"element_id": element_id})


@mcp.tool()
async def get_p13_dimension_types() -> dict:
    """List the DimensionType styles available in the active Revit model."""
    return await post_route("dimension_types", {})


@mcp.tool()
async def analyze_p13_dimension_patterns(limit: int = 5000) -> dict:
    """Learn dimension conventions from dimensions already placed in the model.

    The analysis groups evidence by DimensionType, view type, scale, referenced
    category, direction, segment count, and equality usage. No model data is sent
    to another service by this local P13 tool.
    """
    return await post_route("dimension_patterns", {"limit": limit})


@mcp.tool()
async def recommend_p13_dimension_style(
    element_ids: Optional[List[int]] = None,
    direction: str = "auto",
    dimension_type_id: Optional[int] = None,
) -> dict:
    """Recommend a DimensionType from active-model evidence and accepted history.

    If element_ids is omitted, the current Revit selection is used. direction
    may be auto, horizontal, vertical, or aligned. An explicit dimension_type_id
    overrides learning while still validating that the type exists.
    """
    return await post_route(
        "recommend_dimension",
        {
            "element_ids": element_ids or [],
            "direction": direction,
            "dimension_type_id": dimension_type_id,
        },
    )


@mcp.tool()
async def preview_p13_auto_dimension(
    element_ids: Optional[List[int]] = None,
    direction: str = "auto",
    reference_side: str = "auto",
    offset_mm: float = 1000.0,
    dimension_type_id: Optional[int] = None,
) -> dict:
    """Preview a learned automatic dimension without changing the model.

    Uses the current Revit selection when element_ids is omitted. direction may
    be auto, horizontal, vertical, or aligned. reference_side may be auto,
    center, start, end, or both. The result contains a preview_signature required by the
    apply tool and identifies unsupported elements before any transaction starts.
    """
    return await post_route(
        "preview_auto_dimension",
        {
            "element_ids": element_ids or [],
            "direction": direction,
            "reference_side": reference_side,
            "offset_mm": offset_mm,
            "dimension_type_id": dimension_type_id,
        },
    )


@mcp.tool()
async def apply_p13_auto_dimension(
    preview_signature: str,
    element_ids: Optional[List[int]] = None,
    direction: str = "auto",
    reference_side: str = "auto",
    offset_mm: float = 1000.0,
    dimension_type_id: Optional[int] = None,
    confirm_write: bool = False,
) -> dict:
    """Create the exact auto-dimension operation previously previewed.

    This model-writing tool requires both the matching preview_signature and
    confirm_write=true. It never applies an EQ constraint, so P13 does not
    redistribute or move the referenced source elements. A successful accepted
    style is remembered locally for matching future contexts.
    """
    blocked = host_write_blocked(confirm_write)
    if blocked:
        return blocked
    return await post_route(
        "apply_auto_dimension",
        {
            "preview_signature": preview_signature,
            "element_ids": element_ids or [],
            "direction": direction,
            "reference_side": reference_side,
            "offset_mm": offset_mm,
            "dimension_type_id": dimension_type_id,
            "confirm_write": confirm_write,
        },
    )


@mcp.tool()
async def preview_p13_ai_auto_dimension_plan(
    element_ids: Optional[List[int]] = None,
    direction: str = "auto",
    reference_side: str = "auto",
    offset_mm: float = 1000.0,
    dimension_type_id: Optional[int] = None,
    skip_duplicates: bool = True,
) -> dict:
    """Plan and preview a safe learned dimension in the active plan view.

    The result explains every planned step, identifies exact duplicate
    dimensions, preserves unequal intervals, and provides the preview signature
    required to apply. This tool never modifies the Revit model.
    """
    return await post_route(
        "hot_dispatch",
        {
            "action": "preview",
            "operation": "ai_auto_dimension_plan",
            "payload": {
                "element_ids": element_ids or [],
                "direction": direction,
                "reference_side": reference_side,
                "offset_mm": offset_mm,
                "dimension_type_id": dimension_type_id,
                "skip_duplicates": skip_duplicates,
            },
        },
    )


@mcp.tool()
async def apply_p13_ai_auto_dimension_plan(
    preview_signature: str,
    element_ids: Optional[List[int]] = None,
    direction: str = "auto",
    reference_side: str = "auto",
    offset_mm: float = 1000.0,
    dimension_type_id: Optional[int] = None,
    skip_duplicates: bool = True,
    confirm_write: bool = False,
) -> dict:
    """Apply and verify the exact AI auto-dimension plan previously previewed.

    The operation requires confirm_write=true, rolls back on verification
    failure, never adds EQ constraints, and records a local audit entry.
    """
    blocked = host_write_blocked(confirm_write)
    if blocked:
        return blocked
    return await post_route(
        "hot_dispatch",
        {
            "action": "apply",
            "operation": "ai_auto_dimension_plan",
            "preview_signature": preview_signature,
            "confirm_write": confirm_write,
            "payload": {
                "element_ids": element_ids or [],
                "direction": direction,
                "reference_side": reference_side,
                "offset_mm": offset_mm,
                "dimension_type_id": dimension_type_id,
                "skip_duplicates": skip_duplicates,
            },
        },
    )


@mcp.tool()
async def preview_p13_view_annotation_sync(
    source_view_id: int,
    target_view_id: int,
    include_tags: bool = True,
    include_dimensions: bool = True,
    align_target_scale: bool = False,
    mode: str = "replace",
) -> dict:
    """Preview replacement of target-view tags and dimensions from a source view.

    The source and target must be non-template views with matching view type and
    scale unless align_target_scale is true. Only view-owned tags and dimensions
    are included. Equality-constrained source dimensions block apply because they
    could reposition model elements.
    """
    return await post_route(
        "preview_view_annotation_sync",
        {
            "source_view_id": source_view_id,
            "target_view_id": target_view_id,
            "include_tags": include_tags,
            "include_dimensions": include_dimensions,
            "align_target_scale": align_target_scale,
            "mode": mode,
        },
    )


@mcp.tool()
async def apply_p13_view_annotation_sync(
    preview_signature: str,
    source_view_id: int,
    target_view_id: int,
    include_tags: bool = True,
    include_dimensions: bool = True,
    align_target_scale: bool = False,
    mode: str = "replace",
    confirm_write: bool = False,
) -> dict:
    """Apply an exact, previously previewed tag and dimension view sync.

    This atomic model-writing operation requires the matching preview signature
    and confirm_write=true. It replaces only target view-owned tags and
    dimensions; it does not move model elements.
    """
    blocked = host_write_blocked(confirm_write)
    if blocked:
        return blocked
    return await post_route(
        "apply_view_annotation_sync",
        {
            "preview_signature": preview_signature,
            "source_view_id": source_view_id,
            "target_view_id": target_view_id,
            "include_tags": include_tags,
            "include_dimensions": include_dimensions,
            "align_target_scale": align_target_scale,
            "mode": mode,
            "confirm_write": confirm_write,
        },
    )


@mcp.tool()
async def list_p13_hot_operations() -> dict:
    """List allowlisted Revit operations available through the hot-load bridge.

    Operation manifest and module changes are detected by Revit without a
    pyRevit reload. Arbitrary code supplied by an MCP client is never executed.
    """
    return await post_route("hot_operations", {})


@mcp.tool()
async def execute_p13_hot_operation(
    operation: str,
    payload: Optional[Dict[str, Any]] = None,
) -> dict:
    """Execute an allowlisted read-only operation loaded from the P13 operation registry."""
    return await post_route(
        "hot_dispatch",
        {
            "action": "execute",
            "operation": operation,
            "payload": payload or {},
        },
    )


@mcp.tool()
async def preview_p13_hot_operation(
    operation: str,
    payload: Optional[Dict[str, Any]] = None,
) -> dict:
    """Preview an allowlisted write operation without changing the Revit model."""
    return await post_route(
        "hot_dispatch",
        {
            "action": "preview",
            "operation": operation,
            "payload": payload or {},
        },
    )


@mcp.tool()
async def apply_p13_hot_operation(
    operation: str,
    preview_signature: str,
    payload: Optional[Dict[str, Any]] = None,
    confirm_write: bool = False,
) -> dict:
    """Apply an exact hot-operation preview with explicit write confirmation."""
    blocked = host_write_blocked(confirm_write)
    if blocked:
        return blocked
    return await post_route(
        "hot_dispatch",
        {
            "action": "apply",
            "operation": operation,
            "payload": payload or {},
            "preview_signature": preview_signature,
            "confirm_write": confirm_write,
        },
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run the provider-neutral P13 Revit MCP server."
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http", "http"],
        default="stdio",
        help=(
            "MCP transport. Use stdio for local desktop clients, "
            "streamable-http/http for modern HTTP clients, or sse for legacy clients."
        ),
    )
    parser.add_argument(
        "--host",
        choices=["127.0.0.1", "localhost", "::1"],
        default="127.0.0.1",
        help="Loopback interface for HTTP transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_configured_port,
        help="Local port for HTTP transports. Default: 8013.",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="Return JSON responses instead of SSE-formatted responses for Streamable HTTP.",
    )
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="Use stateless Streamable HTTP sessions for compatible gateways.",
    )
    return parser.parse_args()


def run_server():
    arguments = parse_arguments()
    transport = (
        "streamable-http" if arguments.transport == "http" else arguments.transport
    )
    if arguments.port < 1 or arguments.port > 65535:
        raise ValueError("port must be between 1 and 65535")

    mcp.settings.host = arguments.host
    mcp.settings.port = arguments.port
    mcp.settings.json_response = bool(arguments.json_response)
    mcp.settings.stateless_http = bool(arguments.stateless_http)
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_server()
