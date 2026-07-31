# P13 Revit MCP Security Policy

## Supported deployment

P13 Revit MCP is supported as a per-user local integration on Windows with
Revit and pyRevit. Use stdio where the AI client supports it. Streamable HTTP
and SSE must remain bound to a loopback address and use port 8013 with bearer
authentication.

Do not expose ports 8013 or 48884 directly to a LAN or the public Internet. A
remote deployment requires a separately managed TLS/OAuth MCP gateway or a
private VPN with access controls.

## Secrets

Each Windows user receives separate Routes and MCP bearer tokens in:

`%APPDATA%\pyRevit\P13\mcp_config.json`

This file must never be committed, uploaded, included in a release archive, or
shared with another user. Run `configure_clients.py --rotate-mcp-token` if the
HTTP bearer token may have been disclosed. The internal Routes token is not
placed in AI client configurations.

SuperSheet profiles and last-used export paths are stored per user under:

`%APPDATA%\pyRevit\P13\SuperSheet`

They are migrated from legacy extension files on first use and are excluded
from Git and release archives.

## AI data privacy

P13 hides the active document title and full filesystem path by default. These
fields can be enabled only in the private `mcp_config.json` using
`share_document_title` and `share_document_path`. View names, element metadata,
tags, and dimensions may still be sent when required by an AI task.

The AI Console asks for confirmation before using any remote provider. Local
result history is disabled by default and can be enabled for an individual
task. Ollama and LM Studio can be used when model data must remain local.

## Model-writing policy

Authentication alone does not authorize model changes. P13 write tools require
an explicit `confirm_write=true`. Auto Dimension additionally requires an exact
preview signature. P13 does not expose arbitrary Python, shell, or Revit code
execution.

## Coexistence with other Revit MCP servers

The reference `mcp-server-for-revit-python` uses HTTP port 8000. P13 reserves
port 8013, so both MCP processes can run together. Both route namespaces may
share pyRevit Routes port 48884. Restrict pyRevit Routes to `127.0.0.1` before
enabling third-party route extensions.

The reference server exposes arbitrary Revit code execution and does not add
authentication to pyRevit Routes. P13 security controls do not protect tools or
routes registered by another extension. Prefer running third-party MCP servers
through stdio and disable tools that are not required.

## Reporting a vulnerability

For a public GitHub distribution, use a private GitHub Security Advisory in the
repository rather than opening a public issue containing exploit details or
tokens. Revoke affected tokens before collecting diagnostic logs.

## Public release gate

Before publishing source history, run:

```powershell
uv run security_audit.py --release
```

Before distributing a ZIP, create it from the Git allowlist instead of zipping
the installed extension directory:

```powershell
uv run prepare_release.py C:\Releases\P13.extension.zip
```

The repository audit intentionally fails when secret-shaped values remain in
old Git commits. Deleting a credential from the current file is insufficient:
revoke it, rewrite the affected history, and verify the remote after the
rewrite. Rewriting and force-pushing history must be coordinated with every
repository user and is never performed automatically by P13.
