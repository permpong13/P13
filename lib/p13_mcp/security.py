# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import os
import re
import stat
import uuid
from datetime import datetime


CONFIG_ENVIRONMENT_VARIABLE = "P13_MCP_CONFIG"
CONFIG_VERSION = 3
DEFAULT_ROUTES_URL = "http://127.0.0.1:48884/p13_mcp"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8013

SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{16,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
)


def get_config_path():
    configured_path = os.environ.get(CONFIG_ENVIRONMENT_VARIABLE)
    if configured_path:
        return os.path.abspath(configured_path)

    appdata_path = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata_path, "pyRevit", "P13", "mcp_config.json")


def redact_sensitive_text(value):
    """Remove credentials and user-profile paths from diagnostics."""
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    if user_profile:
        text = text.replace(user_profile, "%USERPROFILE%")
        text = text.replace(user_profile.lower(), "%USERPROFILE%")
    username = os.environ.get("USERNAME") or os.environ.get("USER")
    if username:
        text = re.sub(re.escape(username), "%USERNAME%", text, flags=re.IGNORECASE)
    return text


def write_route_diagnostic(context, error):
    """Write diagnostics without touching pyRevit's WPF output stream.

    Route handlers run on worker threads. Writing to stdout or stderr there can
    make .NET 8 create pyRevit's WPF output window outside the STA thread and
    terminate Revit. This per-user file log is safe during route execution and
    across pyRevit reloads.
    """
    try:
        log_directory = os.path.dirname(get_config_path())
        if not os.path.isdir(log_directory):
            os.makedirs(log_directory)
        log_path = os.path.join(log_directory, "p13_mcp_routes.log")
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        safe_context = redact_sensitive_text(context or "P13 MCP route error").replace("\r", " ").replace("\n", " ")
        safe_error = redact_sensitive_text(error or "Unknown error").replace("\r", " ").replace("\n", " ")
        with open(log_path, "a") as log_file:
            log_file.write("{} | {} | {}\n".format(timestamp, safe_context, safe_error))
    except Exception:
        # Diagnostics must never escape to pyRevit's redirected stderr.
        pass


def _create_token():
    return "{}{}".format(uuid.uuid4().hex, uuid.uuid4().hex)


def _write_private_config(config_path, data):
    temporary_path = config_path + ".tmp"
    with open(temporary_path, "w") as config_file:
        json.dump(data, config_file, indent=2, sort_keys=True)
    try:
        os.chmod(temporary_path, stat.S_IREAD | stat.S_IWRITE)
    except Exception:
        pass
    if os.path.isfile(config_path):
        os.remove(config_path)
    os.rename(temporary_path, config_path)


def _constant_time_equals(value_a, value_b):
    value_a = str(value_a or "")
    value_b = str(value_b or "")
    mismatch = len(value_a) ^ len(value_b)
    maximum_length = max(len(value_a), len(value_b))
    for index in range(maximum_length):
        char_a = ord(value_a[index]) if index < len(value_a) else 0
        char_b = ord(value_b[index]) if index < len(value_b) else 0
        mismatch |= char_a ^ char_b
    return mismatch == 0


def ensure_config():
    config_path = get_config_path()
    config_directory = os.path.dirname(config_path)
    if not os.path.isdir(config_directory):
        os.makedirs(config_directory)

    data = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as config_file:
                data = json.load(config_file)
        except Exception:
            data = {}

    changed = False
    defaults = {
        "config_version": CONFIG_VERSION,
        "token": _create_token(),
        "mcp_token": _create_token(),
        "routes_url": DEFAULT_ROUTES_URL,
        "mcp_http_host": DEFAULT_MCP_HOST,
        "mcp_http_port": DEFAULT_MCP_PORT,
        "network_policy": "loopback_only",
        "share_document_title": False,
        "share_document_path": False,
        "store_ai_history": False,
        "redact_diagnostics": True,
    }
    for key, default_value in defaults.items():
        if not data.get(key):
            data[key] = default_value
            changed = True
    if data.get("config_version") != CONFIG_VERSION:
        data["config_version"] = CONFIG_VERSION
        changed = True
    if data.get("mcp_http_host") not in ("127.0.0.1", "localhost", "::1"):
        data["mcp_http_host"] = DEFAULT_MCP_HOST
        changed = True
    if changed or not os.path.isfile(config_path):
        _write_private_config(config_path, data)
    return data


def parse_request_data(request):
    request_data = getattr(request, "data", None)
    if isinstance(request_data, dict):
        return request_data
    if request_data:
        return json.loads(request_data)
    return {}


def is_authorized(data, config):
    supplied_token = str(data.get("token") or "")
    expected_token = str(config.get("token") or "")
    return bool(expected_token) and _constant_time_equals(
        supplied_token,
        expected_token,
    )
