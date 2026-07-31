# -*- coding: utf-8 -*-
"""Safely configure supported local AI clients for P13 Revit MCP."""

import argparse
import csv
import io
import json
import os
import secrets
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8013
SERVER_NAME = "P13 Revit"
_CURRENT_USER_SID = None


def get_current_user_sid() -> str | None:
    global _CURRENT_USER_SID
    if _CURRENT_USER_SID:
        return _CURRENT_USER_SID
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
        )
        row = next(csv.reader(io.StringIO(result.stdout)))
        _CURRENT_USER_SID = row[1].strip()
        return _CURRENT_USER_SID
    except Exception:
        return None


def get_p13_config_path() -> Path:
    configured_path = os.environ.get("P13_MCP_CONFIG")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "pyRevit" / "P13" / "mcp_config.json"


def make_private(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass
    user_sid = get_current_user_sid()
    if user_sid:
        try:
            subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    "*{}:(F)".format(user_sid),
                    "/grant:r",
                    "*S-1-5-18:(F)",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    make_private(temporary_path)
    os.replace(temporary_path, path)
    make_private(path)


def read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as input_file:
        value = json.load(input_file)
    if not isinstance(value, dict):
        raise ValueError("{} must contain a JSON object.".format(path))
    return value


def ensure_p13_config(rotate_mcp_token: bool = False) -> tuple[Path, dict]:
    path = get_p13_config_path()
    config = read_json_object(path)
    config.setdefault("config_version", 3)
    config.setdefault("token", secrets.token_hex(32))
    config.setdefault("mcp_token", secrets.token_hex(32))
    config.setdefault("routes_url", "http://127.0.0.1:48884/p13_mcp")
    config.setdefault("mcp_http_host", DEFAULT_HOST)
    config.setdefault("mcp_http_port", DEFAULT_PORT)
    config.setdefault("network_policy", "loopback_only")
    config.setdefault("share_document_title", False)
    config.setdefault("share_document_path", False)
    config.setdefault("store_ai_history", False)
    config.setdefault("redact_diagnostics", True)
    if config.get("config_version") != 3:
        config["config_version"] = 3
    if rotate_mcp_token:
        config["mcp_token"] = secrets.token_hex(32)
    if config["mcp_http_host"] not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("P13 MCP host must remain a loopback address.")
    write_json_atomic(path, config)
    return path, config


def backup_file(path: Path) -> Path | None:
    if not path.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name("{}.backup-{}{}".format(path.stem, timestamp, path.suffix))
    shutil.copy2(path, backup_path)
    make_private(backup_path)
    return backup_path


def configure_antigravity(config: dict) -> tuple[Path, Path | None]:
    client_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
    client_config = read_json_object(client_path)
    servers = client_config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers in {} must be a JSON object.".format(client_path))
    port = int(config.get("mcp_http_port") or DEFAULT_PORT)
    servers[SERVER_NAME] = {
        "serverUrl": "http://127.0.0.1:{}/mcp".format(port),
        "headers": {
            "Authorization": "Bearer {}".format(config["mcp_token"]),
        },
    }
    backup_path = backup_file(client_path)
    write_json_atomic(client_path, client_config)
    return client_path, backup_path


def harden_pyrevit_routes() -> tuple[Path | None, Path | None]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None, None
    config_path = Path(appdata) / "pyRevit" / "pyRevit_config.ini"
    if not config_path.is_file():
        return None, None
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped == "[routes]":
            section_start = index
            continue
        if section_start is not None and index > section_start and stripped.startswith("["):
            section_end = index
            break
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[routes]", "host = 127.0.0.1", "port = 48884"])
    else:
        found_host = False
        found_port = False
        for index in range(section_start + 1, section_end):
            key = lines[index].split("=", 1)[0].strip().lower()
            if key == "host":
                lines[index] = "host = 127.0.0.1"
                found_host = True
            elif key == "port":
                lines[index] = "port = 48884"
                found_port = True
        insert_at = section_end
        if not found_host:
            lines.insert(insert_at, "host = 127.0.0.1")
            insert_at += 1
        if not found_port:
            lines.insert(insert_at, "port = 48884")
    new_text = "\n".join(lines) + "\n"
    if new_text == text.replace("\r\n", "\n"):
        return config_path, None
    backup_path = backup_file(config_path)
    temporary_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary_path.write_text(new_text, encoding="utf-8")
    os.replace(temporary_path, config_path)
    return config_path, backup_path


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Configure a local AI client for secured P13 Revit MCP."
    )
    parser.add_argument(
        "--client",
        choices=["antigravity"],
        default="antigravity",
        help="AI client to configure. Default: antigravity.",
    )
    parser.add_argument(
        "--rotate-mcp-token",
        action="store_true",
        help="Generate a new HTTP bearer token and update the selected client.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    config_path, config = ensure_p13_config(arguments.rotate_mcp_token)
    routes_config_path, routes_backup_path = harden_pyrevit_routes()
    if arguments.client == "antigravity":
        client_path, backup_path = configure_antigravity(config)
    else:
        raise ValueError("Unsupported client: {}".format(arguments.client))
    print("Configured {} for P13 Revit MCP.".format(arguments.client))
    print("P13 private config: {}".format(config_path))
    print("Client config: {}".format(client_path))
    if backup_path:
        print("Previous client config backup: {}".format(backup_path))
    if routes_config_path:
        print("pyRevit Routes restricted to 127.0.0.1:48884 in {}".format(
            routes_config_path
        ))
    if routes_backup_path:
        print("Previous pyRevit config backup: {}".format(routes_backup_path))
    print("Endpoint: http://127.0.0.1:{}/mcp".format(config["mcp_http_port"]))
    print("Bearer token was stored locally and was not printed.")


if __name__ == "__main__":
    main()
