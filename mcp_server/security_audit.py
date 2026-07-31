# -*- coding: utf-8 -*-
"""Read-only security audit for local operation and public distribution."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


SECRET_PATTERN = (
    r"(gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|"
    r"AIza[0-9A-Za-z_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
PRIVATE_TRACKED_FILES = {
    "P13.tab/Manager.panel/SuperSheet.pushbutton/Google_profiles_backup.json",
    "P13.tab/Manager.panel/SuperSheet.pushbutton/OHM2.json",
    "P13.tab/Manager.panel/SuperSheet.pushbutton/OHM COCO.xml",
    "P13.tab/Manager.panel/SuperSheet.pushbutton/p13_last_settings.json",
    "P13.tab/Manager.panel/SuperSheet.pushbutton/p13_supersheet_config.json",
    "P13.tab/Manager.panel/SuperSheet.pushbutton/profiles.json",
}


def get_config_path() -> Path:
    configured_path = os.environ.get("P13_MCP_CONFIG")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "pyRevit" / "P13" / "mcp_config.json"


def run_git(extension_root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(extension_root)] + arguments,
        capture_output=True,
        text=True,
        check=False,
    )


def audit_repository(extension_root: Path) -> list[str]:
    failures = []
    tracked_result = run_git(extension_root, ["ls-files"])
    if tracked_result.returncode != 0:
        return ["Git repository metadata could not be inspected."]
    tracked_files = {line.strip() for line in tracked_result.stdout.splitlines()}
    for relative_path in sorted(PRIVATE_TRACKED_FILES.intersection(tracked_files)):
        failures.append("Per-user file is still tracked by Git: {}".format(relative_path))

    current_secret_result = run_git(
        extension_root,
        ["grep", "-I", "-l", "-E", SECRET_PATTERN, "--"],
    )
    if current_secret_result.returncode == 0 and current_secret_result.stdout.strip():
        for path in current_secret_result.stdout.splitlines():
            failures.append("Secret-shaped value exists in a tracked file: {}".format(path))

    history_result = run_git(
        extension_root,
        ["log", "--all", "--format=%H", "-G", SECRET_PATTERN, "--"],
    )
    if history_result.returncode == 0 and history_result.stdout.strip():
        commits = [
            line.strip()
            for line in history_result.stdout.splitlines()
            if re.match(r"^[0-9a-fA-F]{40}$", line.strip())
        ]
        failures.append(
            "Secret-shaped values remain in Git history ({} matching commit(s)). "
            "Revoke the credentials and rewrite history before publishing the repository.".format(
                len(set(commits)) or "unknown"
            )
        )
    return failures


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit P13 MCP security.")
    parser.add_argument(
        "--release",
        action="store_true",
        help="Also fail on tracked private files and secret-shaped Git history.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    config_path = get_config_path()
    failures = []
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    routes_token = str(config.get("token") or "")
    mcp_token = str(config.get("mcp_token") or "")
    if len(routes_token) < 64:
        failures.append("Routes token is missing or too short.")
    if len(mcp_token) < 64:
        failures.append("MCP bearer token is missing or too short.")
    if routes_token == mcp_token:
        failures.append("Routes and MCP tokens must be different.")
    if config.get("mcp_http_host") not in ("127.0.0.1", "localhost", "::1"):
        failures.append("MCP HTTP host is not loopback-only.")
    if int(config.get("mcp_http_port") or 0) != 8013:
        failures.append("P13 MCP should use reserved local port 8013.")
    if config.get("network_policy") != "loopback_only":
        failures.append("Network policy is not loopback_only.")
    if config.get("share_document_title") is not False:
        failures.append("Document titles are shared by default.")
    if config.get("share_document_path") is not False:
        failures.append("Document paths are shared by default.")
    appdata = os.environ.get("APPDATA")
    routes_config_path = (
        Path(appdata) / "pyRevit" / "pyRevit_config.ini" if appdata else None
    )
    routes_loopback_configured = False
    if routes_config_path and routes_config_path.is_file():
        routes_text = routes_config_path.read_text(encoding="utf-8").lower()
        routes_match = re.search(
            r"(?ms)^\s*\[routes\]\s*$([\s\S]*?)(?=^\s*\[|\Z)",
            routes_text,
        )
        routes_section = routes_match.group(1) if routes_match else ""
        routes_loopback_configured = bool(
            re.search(
                r"(?m)^\s*host\s*=\s*[\"']?(?:127\.0\.0\.1|localhost|::1)[\"']?\s*$",
                routes_section,
            )
        )
    if not routes_loopback_configured:
        failures.append("pyRevit Routes is not configured for loopback-only access.")
    extension_root = Path(__file__).resolve().parent.parent
    if arguments.release:
        failures.extend(audit_repository(extension_root))
    print("P13 MCP security audit")
    print("- Config version: {}".format(config.get("config_version")))
    print("- Private config is outside extension: {}".format(
        "P13.extension" not in str(config_path)
    ))
    print("- Routes token present: {}".format(bool(routes_token)))
    print("- Separate MCP token present: {}".format(bool(mcp_token)))
    print("- Bind policy: {}".format(config.get("network_policy")))
    print("- HTTP port: {}".format(config.get("mcp_http_port")))
    print("- Document title shared: {}".format(config.get("share_document_title")))
    print("- Document path shared: {}".format(config.get("share_document_path")))
    print("- pyRevit Routes loopback configured: {}".format(
        routes_loopback_configured
    ))
    if failures:
        for failure in failures:
            print("FAIL: {}".format(failure))
        raise SystemExit(1)
    print("PASS: {} security configuration is valid.".format(
        "Local and release" if arguments.release else "Local"
    ))


if __name__ == "__main__":
    main()
