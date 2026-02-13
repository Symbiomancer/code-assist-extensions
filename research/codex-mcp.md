# OpenAI Codex CLI MCP Extension Mechanism

## Overview
Codex CLI supports MCP servers for extending capabilities with third-party tools. Configuration is stored in `config.toml` (TOML format, not JSON).

## Transport Types
- **stdio**: Local process started by command
- **Streamable HTTP**: Remote server accessed via URL

## Configuration Locations
- **Global**: `~/.codex/config.toml`
- **Project scope**: `.codex/config.toml` (trusted projects only)
- CLI and IDE extension share configuration

## Adding Servers

### CLI Method
```bash
codex mcp add <server-name> --env VAR1=VALUE1 -- <command>
codex mcp add shopping-assistant -- python -m shopping_tool
```

### Config File (config.toml)

#### Stdio Server
```toml
[mcp_servers.shopping-assistant]
command = "python"
args = ["-m", "shopping_tool"]
tool_timeout_sec = 120

[mcp_servers.shopping-assistant.env]
OPENROUTER_API_KEY = "your-key"
SHOPPING_HEADLESS = "false"
```

#### HTTP Server
```toml
[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"
bearer_token_env_var = "FIGMA_OAUTH_TOKEN"
http_headers = { "X-Region" = "us-east-1" }
```

## Configuration Parameters

### Stdio Servers
| Parameter | Required | Purpose |
|-----------|----------|---------|
| `command` | Yes | Server startup command |
| `args` | No | Command arguments (array of strings) |
| `env` | No | Environment variables (table) |
| `env_vars` | No | Variables to forward from host |
| `cwd` | No | Working directory |

### HTTP Servers
| Parameter | Required | Purpose |
|-----------|----------|---------|
| `url` | Yes | Server address |
| `bearer_token_env_var` | No | Env var name for Bearer auth |
| `http_headers` | No | Static HTTP headers |
| `env_http_headers` | No | Headers sourced from env vars |

### Universal Options
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `startup_timeout_sec` | 10 | Time to wait for server start |
| `tool_timeout_sec` | 60 | Per-tool execution timeout |
| `enabled` | true | Enable/disable server |
| `required` | false | Fail startup if server unavailable |
| `enabled_tools` | [] | Allowlist of tool names |
| `disabled_tools` | [] | Denylist of tool names |

## Management
- `/mcp` in TUI to view active servers
- `codex mcp add/remove` for CLI management
- Session-scoped "Allow and remember" for tool approvals (Feb 2026)

## OAuth
Set `mcp_oauth_callback_port` at top level of config.toml for OAuth callback.

## Sources
- https://developers.openai.com/codex/mcp/
- https://developers.openai.com/codex/cli/reference/
