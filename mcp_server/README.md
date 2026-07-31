# P13 Revit MCP

This is a provider-neutral, local MCP bridge for P13 pyRevit automation.
It does not expose arbitrary Python code execution. Any AI application that
implements the MCP standard can discover and call the same tools.

## Revit setup

1. In pyRevit Settings, enable the Routes Server.
2. Reload pyRevit or restart Revit.
3. Confirm that this URL responds:
   `http://127.0.0.1:48884/p13_mcp/status/`

On first load, P13 creates a private local configuration at:
`%APPDATA%\pyRevit\P13\mcp_config.json`

The file is created separately for every Windows user. It contains two distinct
random secrets: one for the internal pyRevit Routes bridge and one bearer token
for HTTP MCP clients. Never commit or share this file.

## Supported AI clients

The server is not tied to an AI model or vendor. It can be used by:

- OpenAI/Codex clients with MCP support
- Claude Desktop and Claude Code
- VS Code and GitHub Copilot agents
- Cursor and other MCP-compatible editors
- Gemini or other provider agents through an MCP-capable host
- Local models through MCP-capable applications
- Custom agents using the official MCP SDK or the secured HTTP routes

An AI model by itself does not connect to tools. Its host application must
support MCP or provide an MCP/HTTP adapter.

## P13 AI Console ribbon command

`P13 > AI Tools > P13 AI Console` is the built-in provider and model launcher.
It supports:

- OpenAI Codex with an existing ChatGPT desktop or CLI sign-in
- OpenAI API
- Anthropic API
- Google Gemini API
- OpenRouter
- Ollama on loopback port `11434`
- LM Studio on loopback port `1234`
- A custom OpenAI-compatible HTTP API

Cloud credentials are read from Windows user environment variables and are
never written to the extension, request files, result history, console output,
or MCP calls:

| Provider | User environment variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Custom compatible API | `P13_CUSTOM_AI_API_KEY` (optional) |

The Codex provider does not require `OPENAI_API_KEY`. It discovers the Codex
CLI installed with the ChatGPT desktop app, reuses the cached ChatGPT sign-in,
loads the current Codex model catalog, and injects the P13 stdio MCP
configuration for each task. The per-task MCP configuration works even when
`p13_revit` is not permanently listed in `~/.codex/config.toml`.

Use **Refresh Models** to query the provider's current model catalog, or type a
valid model ID directly. Provider and model selections are remembered per
pyRevit user. Prompts and API keys are not saved in pyRevit settings. A local
result history is stored in `%APPDATA%\pyRevit\P13\ai_history`; the temporary
request file is removed as soon as the external agent reads it.

The launcher opens a separate PowerShell task window and starts the MCP server
over stdio for that task. Streamable HTTP port `8013` is not required and there
is no port collision with another Revit MCP server. The Revit document remains
available to the Routes/ExternalEvent workflow while the AI is running.

Write permission is disabled by default. Enabling it requires an additional
confirmation for that task, while each write-capable MCP tool still enforces
its own `confirm_write=true` and preview-signature requirements. Fixed cloud API
URLs cannot be redirected to another host, and local provider URLs must remain
on a loopback address to protect credentials and model data.

Signing in to a desktop AI application does not automatically share that
application's private login session with P13 AI Console. Use the provider API
key environment variable, or run a supported local model server.

## Transport modes

### Stdio — local desktop clients

From this directory:

```powershell
uv run main.py
```

### Streamable HTTP — modern MCP clients

```powershell
uv run main.py --transport streamable-http --port 8013
```

Endpoint: `http://127.0.0.1:8013/mcp`

Browser-friendly health page: `http://127.0.0.1:8013/health`

Do not use the browser response from `/mcp` as a connection test. `/mcp`
requires an MCP client with the correct protocol headers and session handling.

Test discovery from another terminal:

```powershell
uv run smoke_test.py --url http://127.0.0.1:8013/mcp
```

For clients that require plain JSON responses:

```powershell
uv run main.py --transport streamable-http --port 8013 --json-response
```

### SSE — legacy MCP clients

```powershell
uv run main.py --transport sse --port 8013
```

SSE endpoint: `http://127.0.0.1:8013/sse`

Message endpoint: `http://127.0.0.1:8013/messages/`

## Generic stdio client configuration

```json
{
  "mcpServers": {
    "P13 Revit": {
      "command": "uv",
      "args": [
        "--directory",
        "<P13_EXTENSION_PATH>\\mcp_server",
        "run",
        "main.py"
      ]
    }
  }
}
```

## Generic Streamable HTTP client configuration

Start the server in Streamable HTTP mode, then use:

```json
{
  "servers": {
    "P13 Revit": {
      "type": "http",
      "serverUrl": "http://127.0.0.1:8013/mcp",
      "headers": {
        "Authorization": "Bearer <PER_USER_MCP_TOKEN>"
      }
    }
  }
}
```

Some clients use `mcpServers` instead of `servers`; use the schema required by
that client while keeping the command, arguments, or URL unchanged.

For Antigravity, configure the correct path and bearer header automatically:

```powershell
uv run configure_clients.py --client antigravity
```

The configurator preserves other MCP entries, creates a timestamped backup,
stores the token without printing it, and writes the endpoint using Antigravity's
required `serverUrl` field. To revoke existing HTTP client access and issue a new
token:

```powershell
uv run configure_clients.py --client antigravity --rotate-mcp-token
```

## Included tools

- `get_p13_revit_status`
- `get_p13_document_info`
- `get_p13_active_view`
- `get_p13_selected_elements`
- `manage_p13_grid_bubbles`
- `get_p13_model_summary`
- `get_p13_levels`
- `get_p13_views`
- `get_p13_active_view_elements`
- `get_p13_element_parameters`
- `get_p13_dimension_types`
- `analyze_p13_dimension_patterns`
- `recommend_p13_dimension_style`
- `preview_p13_auto_dimension`
- `apply_p13_auto_dimension`
- `preview_p13_ai_auto_dimension_plan`
- `apply_p13_ai_auto_dimension_plan`

All model-writing calls require explicit `confirm_write=true`.

## Adaptive dimension intelligence

P13 learns dimension conventions from the active model instead of sending BIM
data to a cloud model. Existing dimensions provide evidence for DimensionType,
view type, view scale, referenced categories, direction, segment count, and EQ
usage. Recommendations favor the active view first, then matching view type,
scale, categories, and direction.

The safe workflow is:

1. `analyze_p13_dimension_patterns` inspects existing work.
2. `recommend_p13_dimension_style` explains the recommended style and score.
3. `preview_p13_auto_dimension` validates references and returns a signature.
4. The user reviews the preview.
5. `apply_p13_auto_dimension` requires the same signature and
   `confirm_write=true`.

An accepted DimensionType is remembered in
`%APPDATA%\pyRevit\P13\dimension_learning.json` for the same project, view
context, categories, and direction. The learning file stores context counters,
not model geometry. Auto-dimension never enables an EQ constraint, so P13 does
not redistribute referenced elements. The created dimension still displays real
segment values when gaps are unequal.

## AI Auto Dimension Plan engine

`preview_p13_ai_auto_dimension_plan` is the preferred plan-view workflow. It
returns a human-readable execution plan, exact duplicate detection, measured
intervals, unequal-spacing status, the learned DimensionType recommendation,
unsupported elements, safety checks, and a signed preview. It does not modify
the model.

`apply_p13_ai_auto_dimension_plan` requires the matching signature and
`confirm_write=true`. It creates the dimension inside a transaction group and
verifies that the dimension exists, EQ remains disabled, reference counts match,
and source element locations are unchanged. Any failed verification rolls back
the complete Revit operation. Exact duplicates are reported as a successful
no-change result by default. Successful and no-change results are recorded in
`%APPDATA%\pyRevit\P13\audit\ai_auto_dimension.jsonl`.

The implementation is the allowlisted `ai_auto_dimension_plan` hot operation,
so updates to its operation module and manifest are detected without reloading
pyRevit.

## Hot-loaded operations

P13 registers one stable, authenticated dispatch bridge inside Revit. After the
bridge is installed once, operation modules and the local manifest are read from
`lib\p13_mcp_operations` and refreshed when their file timestamp or size changes.
Adding or updating an allowlisted operation therefore does not require a pyRevit
reload. The generic MCP tools are:

- `list_p13_hot_operations`
- `execute_p13_hot_operation` for read-only operations
- `preview_p13_hot_operation` for model-writing previews
- `apply_p13_hot_operation` with a matching signature and `confirm_write=true`

The bridge never executes Python source supplied by an MCP client. Operation
names must exist in the local `manifest.json`, module paths cannot leave the
operation directory, payload size is limited, and write operations retain the
Preview -> Confirm -> Apply workflow. A pyRevit reload or Revit restart is only
needed when installing or changing the stable bridge itself, not when adding or
editing operation modules.

## One-click Windows launcher

Double-click `Start-P13-MCP.cmd`. Keep the console window open while an AI
client is using Revit. Close it or press `Ctrl+C` to stop the server.

## Security boundary

- HTTP transports bind only to a loopback address.
- Port `8013` is reserved for P13, while the reference Revit MCP can continue on
  port `8000`; both share pyRevit Routes port `48884` under different API names.
- Streamable HTTP and SSE require a per-user bearer token.
- DNS-rebinding protection validates HTTP Host and Origin values.
- The Revit Routes API uses a different private token stored outside the repository.
- The MCP server never exposes the Routes token as a tool result.
- Tokens are generated independently for each Windows user and are excluded from Git.
- Model-writing tools still require explicit confirmation after authentication.
- Remote/cloud access is intentionally disabled by default. Use an authenticated
  TLS MCP gateway or private VPN adapter instead of exposing ports `8013` or
  `48884` directly.
- Do not publish `%APPDATA%\pyRevit\P13\mcp_config.json`.

Run the local read-only audit after installation or upgrades:

```powershell
uv run security_audit.py
```

## Worldwide distribution

P13 is portable across Windows users because no username or installation path is
embedded in runtime code. Distribute the `P13.extension` folder without `.git`,
`.venv`, logs, caches, or `%APPDATA%` configuration files. Each recipient then:

1. Places `P13.extension` in a pyRevit extension directory or registers its
   custom parent directory.
2. Enables pyRevit Routes and reloads pyRevit.
3. Installs `uv` and runs `uv sync` in `P13.extension\mcp_server`.
4. Uses stdio where supported, or runs `Start-P13-MCP.cmd` for authenticated
   local HTTP on port `8013`.
5. Runs `configure_clients.py` for a supported client and keeps all generated
   secrets private.

The configurator also sets pyRevit Routes to `host = 127.0.0.1` and
`port = 48884` in the current user's pyRevit configuration. Restart Revit after
the first installation so the restricted listener replaces any existing
`0.0.0.0` listener.

Stdio is the preferred distribution mode because the AI client launches the MCP
process directly and no listening MCP port is required. HTTP remains local-only.
Publishing a public Internet endpoint is intentionally unsupported by this
package; deploy a separate standards-compliant TLS/OAuth gateway if remote use is
required.

Before publishing a public package, the repository owner must choose and add an
explicit software license. P13 does not inherit the MIT license of the reference
Revit MCP merely because it follows a similar architecture.

## Non-MCP AI platforms

Do not give an AI platform the internal Routes token. A platform without native
MCP support should use a local MCP-capable host or adapter connected to the
authenticated port `8013`. The internal port `48884` and Routes token remain an
implementation boundary between the P13 MCP process and Revit.
