# -*- coding: utf-8 -*-
"""Provider-neutral AI agent that uses the secured P13 Revit MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_DIRECTORY = Path(__file__).resolve().parent
EXTENSION_ROOT = SERVER_DIRECTORY.parent
PROVIDERS_PATH = SERVER_DIRECTORY / "ai_providers.json"
MCP_SERVER_PATH = SERVER_DIRECTORY / "main.py"
DEFAULT_MAX_STEPS = 12
DEFAULT_TIMEOUT_SECONDS = 180.0
MAX_TOOL_RESULT_CHARACTERS = 60000


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as input_file:
        value = json.load(input_file)
    if not isinstance(value, dict):
        raise ValueError("{} must contain a JSON object.".format(path))
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(value, output_file, indent=2, ensure_ascii=False)
        output_file.write("\n")
    os.replace(temporary_path, path)


def load_providers() -> list[dict[str, Any]]:
    value = load_json_object(PROVIDERS_PATH)
    providers = value.get("providers")
    if not isinstance(providers, list):
        raise ValueError("ai_providers.json must contain a providers list.")
    return [provider for provider in providers if isinstance(provider, dict)]


def get_provider(provider_id: str) -> dict[str, Any]:
    for provider in load_providers():
        if provider.get("id") == provider_id:
            return provider
    raise ValueError("Unknown AI provider: {}".format(provider_id))


def get_environment_value(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value or "")
    except (OSError, ImportError):
        return ""


def get_api_key(provider: dict[str, Any]) -> tuple[str, str]:
    for environment_name in provider.get("api_key_env") or []:
        value = get_environment_value(str(environment_name))
        if value:
            return value, str(environment_name)
    if provider.get("requires_api_key"):
        names = ", ".join(provider.get("api_key_env") or [])
        raise ValueError(
            "No API key was found. Set one of these user environment variables: {}".format(
                names
            )
        )
    return "", ""


def find_codex_cli() -> Path:
    configured_path = get_environment_value("P13_CODEX_CLI")
    if configured_path and Path(configured_path).is_file():
        return Path(configured_path).resolve()
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        built_in_candidates = [
            path
            for path in
            (Path(local_appdata) / "OpenAI" / "Codex" / "bin").glob(
                "*/codex.exe"
            )
            if path.is_file()
        ]
        if built_in_candidates:
            return max(
                built_in_candidates, key=lambda path: path.stat().st_mtime
            ).resolve()
    local_candidates = list(
        (EXTENSION_ROOT / ".codex-cli" / "node_modules" / "@openai").glob(
            "codex-win32-*/vendor/*/bin/codex.exe"
        )
    )
    existing = [path for path in local_candidates if path.is_file()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime).resolve()
    command_path = shutil.which("codex")
    if command_path and Path(command_path).is_file():
        return Path(command_path).resolve()
    raise ValueError(
        "Codex CLI was not found. Install the ChatGPT desktop app or set P13_CODEX_CLI."
    )


def find_uv() -> Path:
    command_path = shutil.which("uv")
    if command_path and Path(command_path).is_file():
        return Path(command_path).resolve()
    candidate = Path.home() / ".local" / "bin" / "uv.exe"
    if candidate.is_file():
        return candidate.resolve()
    raise ValueError("uv was not found. Install uv before using P13 Revit MCP.")


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def validate_base_url(provider: dict[str, Any], value: str) -> str:
    base_url = normalize_base_url(value)
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("The provider base URL must use http:// or https://.")
    policy = str(provider.get("base_url_policy") or "fixed")
    configured_url = normalize_base_url(provider.get("base_url"))
    if policy == "fixed" and base_url != configured_url:
        raise ValueError(
            "{} uses a fixed trusted base URL: {}".format(
                provider.get("name"), configured_url
            )
        )
    if policy == "loopback" and parsed.hostname.lower() not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise ValueError("Local AI provider URLs must remain on the loopback interface.")
    return base_url


def endpoint_url(base_url: str, endpoint: str) -> str:
    return "{}/{}".format(normalize_base_url(base_url), endpoint.lstrip("/"))


def json_text(value: Any, limit: int = MAX_TOOL_RESULT_CHARACTERS) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[tool result truncated]"


def serialize_mcp_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json", exclude_none=True)
    content = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "model_dump"):
            content.append(item.model_dump(mode="json", exclude_none=True))
        else:
            content.append({"type": "text", "text": str(item)})
    return {
        "isError": bool(getattr(result, "isError", False)),
        "content": content,
    }


def tool_wants_write(arguments: dict[str, Any]) -> bool:
    if not isinstance(arguments, dict):
        return False
    for key, value in arguments.items():
        if str(key).lower() == "confirm_write":
            if value is True or value == 1:
                return True
            if isinstance(value, str) and value.strip().lower() in (
                "true",
                "yes",
                "1",
            ):
                return True
        if isinstance(value, dict) and tool_wants_write(value):
            return True
    return False


def build_system_prompt(allow_write: bool) -> str:
    write_policy = (
        "The user explicitly enabled Revit changes for this task. Use preview tools "
        "before apply tools whenever a preview workflow exists. Set confirm_write=true "
        "only when the requested change is clear, the preview is safe, and the apply "
        "arguments exactly match the preview."
        if allow_write
        else
        "This task is read-only. Never set confirm_write=true and never attempt to "
        "apply or execute a model-changing operation. You may analyze data and create "
        "previews. Explain which write permission would be required for a change."
    )
    return (
        "You are P13 AI Console, a BIM automation assistant working with Autodesk Revit "
        "2026 through allowlisted P13 MCP tools. Inspect the active document and view "
        "when the request depends on model context. Never invent element IDs, view IDs, "
        "tool results, or completed changes. Keep model data private and send only the "
        "minimum tool context required to the AI provider. {} Return a concise final "
        "summary with what was inspected, what changed, and any blocked or failed step."
    ).format(write_policy)


class ToolRuntime:
    def __init__(self, session: ClientSession, allow_write: bool):
        self.session = session
        self.allow_write = allow_write
        self.call_count = 0

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        print("MCP tool {}: {}".format(self.call_count, name), flush=True)
        if tool_wants_write(arguments) and not self.allow_write:
            return {
                "status": "blocked",
                "reason": (
                    "The user did not enable Revit changes for this AI task. "
                    "Run a new task with write permission enabled."
                ),
            }
        try:
            result = await self.session.call_tool(name, arguments or {})
            return serialize_mcp_result(result)
        except Exception as error:
            return {
                "status": "error",
                "error": str(error),
                "tool": name,
            }


def mcp_tools_to_openai(tools: list[Any]) -> list[dict[str, Any]]:
    output = []
    for tool in tools:
        output.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return output


def mcp_tools_to_anthropic(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in tools
    ]


def sanitize_gemini_schema(schema: Any) -> dict[str, Any]:
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(mode="json", exclude_none=True)
    if not isinstance(schema, dict):
        return {"type": "OBJECT", "properties": {}}

    output: dict[str, Any] = {}

    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        output["type"] = raw_type.upper()
    elif "properties" in schema:
        output["type"] = "OBJECT"
    else:
        output["type"] = "STRING"

    if "description" in schema and schema["description"]:
        output["description"] = str(schema["description"])[:1024]

    if "properties" in schema and isinstance(schema["properties"], dict):
        props = {}
        for name, prop_def in schema["properties"].items():
            props[name] = sanitize_gemini_schema(prop_def)
        output["properties"] = props

    if "required" in schema and isinstance(schema["required"], list):
        output["required"] = [str(req) for req in schema["required"]]

    if "items" in schema and schema["items"]:
        output["items"] = sanitize_gemini_schema(schema["items"])

    if "enum" in schema and isinstance(schema["enum"], list):
        output["enum"] = [str(val) for val in schema["enum"]]

    return output


def mcp_tools_to_gemini(tools: list[Any]) -> list[dict[str, Any]]:
    declarations = []
    for tool in tools:
        declarations.append(
            {
                "name": tool.name,
                "description": (tool.description or "")[:1024],
                "parameters": sanitize_gemini_schema(
                    getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
                ),
            }
        )
    return [{"functionDeclarations": declarations}]


async def run_openai_agent(
    provider: dict[str, Any],
    model: str,
    base_url: str,
    api_key: str,
    prompt: str,
    tools: list[Any],
    runtime: ToolRuntime,
    max_steps: int,
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer {}".format(api_key)
    if provider.get("id") == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/P13/P13.extension"
        headers["X-Title"] = "P13 AI Console"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(runtime.allow_write)},
        {"role": "user", "content": prompt},
    ]
    provider_tools = mcp_tools_to_openai(tools)
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for step in range(1, max_steps + 1):
            print("AI step {} of {}...".format(step, max_steps), flush=True)
            payload = {
                "model": model,
                "messages": messages,
                "tools": provider_tools,
                "tool_choice": "auto",
            }
            response = await client.post(
                endpoint_url(base_url, "chat/completions"),
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("The AI provider returned no choices.")
            message = choices[0].get("message") or {}
            tool_calls = message.get("tool_calls") or []
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            if not tool_calls:
                return str(message.get("content") or "The AI returned no final text.")
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                name = str(function.get("name") or "")
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = await runtime.call(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": name,
                        "content": json_text(result),
                    }
                )
    raise RuntimeError("The AI reached the maximum number of tool steps.")


async def run_anthropic_agent(
    model: str,
    base_url: str,
    api_key: str,
    prompt: str,
    tools: list[Any],
    runtime: ToolRuntime,
    max_steps: int,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    provider_tools = mcp_tools_to_anthropic(tools)
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for step in range(1, max_steps + 1):
            print("AI step {} of {}...".format(step, max_steps), flush=True)
            response = await client.post(
                endpoint_url(base_url, "messages"),
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": build_system_prompt(runtime.allow_write),
                    "messages": messages,
                    "tools": provider_tools,
                },
            )
            response.raise_for_status()
            data = response.json()
            blocks = data.get("content") or []
            messages.append({"role": "assistant", "content": blocks})
            tool_blocks = [block for block in blocks if block.get("type") == "tool_use"]
            if not tool_blocks:
                text_blocks = [
                    str(block.get("text") or "")
                    for block in blocks
                    if block.get("type") == "text"
                ]
                return "\n".join(text_blocks).strip() or "The AI returned no final text."
            tool_results = []
            for block in tool_blocks:
                result = await runtime.call(
                    str(block.get("name") or ""), block.get("input") or {}
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": json_text(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
    raise RuntimeError("The AI reached the maximum number of tool steps.")


async def run_gemini_agent(
    model: str,
    base_url: str,
    api_key: str,
    prompt: str,
    tools: list[Any],
    runtime: ToolRuntime,
    max_steps: int,
) -> str:
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": prompt}]}
    ]
    provider_tools = mcp_tools_to_gemini(tools)
    url = endpoint_url(base_url, "models/{}:generateContent".format(model))
    if api_key and "?key=" not in url:
        url = "{}?key={}".format(url, api_key)
    timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for step in range(1, max_steps + 1):
            print("AI step {} of {}...".format(step, max_steps), flush=True)
            response = await client.post(
                url,
                headers=headers,
                json={
                    "systemInstruction": {
                        "parts": [{"text": build_system_prompt(runtime.allow_write)}]
                    },
                    "contents": contents,
                    "tools": provider_tools,
                },
            )
            if response.status_code != 200:
                err_text = response.text
                print("Gemini API HTTP Error ({}): {}".format(response.status_code, err_text), flush=True)
                raise RuntimeError("Gemini API Error ({}): {}".format(response.status_code, err_text))
            data = response.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise RuntimeError("The Gemini provider returned no candidates.")
            content = candidates[0].get("content") or {"role": "model", "parts": []}
            contents.append(content)
            parts = content.get("parts") or []
            calls = [part.get("functionCall") for part in parts if part.get("functionCall")]
            if not calls:
                texts = [str(part.get("text") or "") for part in parts if "text" in part]
                return "\n".join(texts).strip() or "The AI returned no final text."
            result_parts = []
            for call in calls:
                name = str(call.get("name") or "")
                result = await runtime.call(name, call.get("args") or {})
                result_parts.append(
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": result},
                        }
                    }
                )
            contents.append({"role": "user", "parts": result_parts})
    raise RuntimeError("The AI reached the maximum number of tool steps.")


async def run_codex_cli_agent(
    model: str,
    prompt: str,
    allow_write: bool,
    job_id: str,
) -> str:
    codex_path = find_codex_cli()
    final_message_path = get_history_directory() / "{}.codex-final.txt".format(
        job_id
    )
    final_message_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["P13_MCP_HOST_WRITE_POLICY"] = "allow" if allow_write else "deny"
    full_prompt = "{}\n\nUser task:\n{}".format(
        build_system_prompt(allow_write), prompt
    )
    mcp_arguments = [
        "--directory",
        str(SERVER_DIRECTORY),
        "run",
        "main.py",
        "--transport",
        "stdio",
    ]
    arguments = [
        str(codex_path),
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--cd",
        str(EXTENSION_ROOT),
        "--config",
        'approval_policy="never"',
        "--config",
        "mcp_servers.p13_revit.command={}".format(json.dumps(str(find_uv()))),
        "--config",
        "mcp_servers.p13_revit.args={}".format(json.dumps(mcp_arguments)),
        "--config",
        'mcp_servers.p13_revit.env_vars=["P13_MCP_HOST_WRITE_POLICY"]',
        "--config",
        "mcp_servers.p13_revit.startup_timeout_sec=30",
        "--config",
        "mcp_servers.p13_revit.tool_timeout_sec=180",
        "--config",
        'mcp_servers.p13_revit.default_tools_approval_mode="approve"',
        "--config",
        "mcp_servers.p13_revit.enabled=true",
        "--config",
        "mcp_servers.p13_revit.required=true",
        "--output-last-message",
        str(final_message_path),
        "-",
    ]
    process = await asyncio.create_subprocess_exec(
        *arguments,
        cwd=str(EXTENSION_ROOT),
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("Could not create Codex CLI input and output streams.")
    process.stdin.write(full_prompt.encode("utf-8"))
    await process.stdin.drain()
    process.stdin.close()
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        print(line.decode("utf-8", errors="replace").rstrip(), flush=True)
    return_code = await process.wait()
    final_text = ""
    if final_message_path.is_file():
        final_text = final_message_path.read_text(encoding="utf-8-sig").strip()
        try:
            final_message_path.unlink()
        except OSError:
            pass
    if return_code != 0:
        raise RuntimeError("Codex CLI stopped with exit code {}.".format(return_code))
    return final_text or "Codex completed the task without a final text response."


@asynccontextmanager
async def open_mcp_session():
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_PATH), "--transport", "stdio"],
        cwd=SERVER_DIRECTORY,
        env=dict(os.environ),
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    provider = get_provider(str(request.get("provider_id") or ""))
    model = str(request.get("model") or "").strip()
    prompt = str(request.get("prompt") or "").strip()
    allow_write = bool(request.get("allow_write", False))
    max_steps = int(request.get("max_steps") or DEFAULT_MAX_STEPS)
    max_steps = max(1, min(max_steps, 30))
    if not model:
        raise ValueError("A model ID is required.")
    if not prompt:
        raise ValueError("A task prompt is required.")
    if len(prompt) > 50000:
        raise ValueError("The task prompt exceeds the 50,000 character safety limit.")
    protocol = str(provider.get("protocol") or "openai")

    print("Provider: {}".format(provider.get("name")), flush=True)
    print("Model: {}".format(model), flush=True)
    print("Revit changes: {}".format("enabled" if allow_write else "read-only"), flush=True)
    if protocol == "codex_cli":
        print("Authentication: existing ChatGPT sign-in", flush=True)
        print("Connecting Codex CLI to P13 Revit MCP...", flush=True)
        final_text = await run_codex_cli_agent(
            model,
            prompt,
            allow_write,
            str(request.get("job_id") or "p13-ai"),
        )
        return {
            "status": "completed",
            "provider_id": provider.get("id"),
            "provider": provider.get("name"),
            "model": model,
            "allow_write": allow_write,
            "tool_call_count": None,
            "final": final_text,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    base_url = validate_base_url(
        provider, request.get("base_url") or provider.get("base_url")
    )
    api_key, key_environment = get_api_key(provider)
    if key_environment:
        print("Credential source: {}".format(key_environment), flush=True)
    print("Connecting to P13 Revit MCP...", flush=True)

    async with open_mcp_session() as session:
        listed_tools = await session.list_tools()
        tools = listed_tools.tools
        print("Available P13 MCP tools: {}".format(len(tools)), flush=True)
        runtime = ToolRuntime(session, allow_write)
        if protocol == "anthropic":
            final_text = await run_anthropic_agent(
                model, base_url, api_key, prompt, tools, runtime, max_steps
            )
        elif protocol == "gemini":
            final_text = await run_gemini_agent(
                model, base_url, api_key, prompt, tools, runtime, max_steps
            )
        else:
            final_text = await run_openai_agent(
                provider,
                model,
                base_url,
                api_key,
                prompt,
                tools,
                runtime,
                max_steps,
            )
    return {
        "status": "completed",
        "provider_id": provider.get("id"),
        "provider": provider.get("name"),
        "model": model,
        "allow_write": allow_write,
        "tool_call_count": runtime.call_count,
        "final": final_text,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def discover_models(provider_id: str, base_url_override: str) -> list[str]:
    provider = get_provider(provider_id)
    protocol = provider.get("protocol")
    if protocol == "codex_cli":
        process = await asyncio.create_subprocess_exec(
            str(find_codex_cli()),
            "debug",
            "models",
            "--bundled",
            cwd=str(EXTENSION_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                stderr.decode("utf-8", errors="replace").strip()
                or "Codex model discovery failed."
            )
        data = json.loads(stdout.decode("utf-8-sig"))
        models = []
        for item in data.get("models") or []:
            if not isinstance(item, dict) or item.get("visibility") == "hide":
                continue
            model_id = item.get("slug") or item.get("id")
            if model_id:
                models.append(str(model_id))
        return models
    base_url = validate_base_url(
        provider, base_url_override or provider.get("base_url")
    )
    api_key, _ = get_api_key(provider)
    headers = {"Accept": "application/json"}
    if protocol == "anthropic":
        headers.update(
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        )
    elif protocol == "gemini":
        headers["x-goog-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = "Bearer {}".format(api_key)

    url = endpoint_url(base_url, "models")
    if protocol == "gemini" and api_key and "?key=" not in url:
        url = "{}?key={}".format(url, api_key)
    timeout = httpx.Timeout(30.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    models = []
    for item in data.get("data") or data.get("models") or []:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model")
        if not model_id:
            continue
        model_id = str(model_id)
        if model_id.startswith("models/"):
            model_id = model_id[len("models/") :]
        methods = item.get("supportedGenerationMethods")
        if methods and "generateContent" not in methods:
            continue
        models.append(model_id)
    return sorted(set(models), key=str.lower)


def get_history_directory() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "pyRevit" / "P13" / "ai_history"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run P13 AI Console tasks.")
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--base-url", default="")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.list_models:
        if not arguments.provider:
            raise ValueError("--provider is required with --list-models")
        try:
            models = asyncio.run(
                discover_models(arguments.provider, arguments.base_url)
            )
            print(json.dumps({"status": "ok", "models": models}))
            return 0
        except Exception as error:
            print(json.dumps({"status": "error", "error": str(error)}))
            return 1

    if not arguments.request_file:
        raise ValueError("--request-file is required")
    request_path = arguments.request_file.resolve()
    request = load_json_object(request_path)
    try:
        request_path.unlink()
    except OSError:
        pass
    job_id = str(request.get("job_id") or arguments.request_file.stem)
    history_path = get_history_directory() / "{}.result.json".format(job_id)
    save_history = bool(request.get("save_history", False))
    try:
        result = asyncio.run(execute_request(request))
        if save_history:
            write_json_atomic(history_path, result)
        print("\nAI result\n---------", flush=True)
        print(result["final"], flush=True)
        if save_history:
            print("\nResult file: {}".format(history_path), flush=True)
        else:
            print("\nResult history was not saved (privacy default).", flush=True)
        return 0
    except Exception as error:
        result = {
            "status": "error",
            "error": str(error),
            "job_id": job_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if save_history:
            write_json_atomic(history_path, result)
        print("\nP13 AI task failed: {}".format(error), file=sys.stderr, flush=True)
        if get_environment_value("P13_AI_DEBUG") == "1":
            traceback.print_exc()
        if save_history:
            print("Result file: {}".format(history_path), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
