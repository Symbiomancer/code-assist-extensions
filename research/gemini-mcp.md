# Google Gemini CLI MCP Extension Mechanism

## Overview
Gemini CLI extends functionality through MCP server integration, configured in `~/.gemini/settings.json`.

## Transport Types
- **stdio**: `command` property — spawns subprocess
- **SSE**: `url` property — Server-Sent Events endpoint
- **HTTP Streaming**: `httpUrl` property — streamable HTTP (takes precedence)

Priority if multiple specified: `httpUrl` > `url` > `command`

## Configuration Location
- `~/.gemini/settings.json` — single config file

## Configuration Format

### settings.json Structure
```json
{
  "mcpServers": {
    "shopping-assistant": {
      "command": "python",
      "args": ["-m", "shopping_tool"],
      "env": {
        "OPENROUTER_API_KEY": "$OPENROUTER_API_KEY",
        "SHOPPING_HEADLESS": "false"
      },
      "timeout": 120000
    }
  },
  "mcp": {
    "allowed": ["shopping-assistant"],
    "excluded": []
  }
}
```

### Configuration Properties

#### Required (one of)
| Property | Transport | Description |
|----------|-----------|-------------|
| `command` | stdio | Command to start server |
| `url` | SSE | SSE endpoint URL |
| `httpUrl` | HTTP | Streamable HTTP URL |

#### Optional
| Property | Type | Description |
|----------|------|-------------|
| `args` | string[] | Command arguments |
| `headers` | object | HTTP headers (for url/httpUrl) |
| `env` | object | Environment variables (`$VAR` expansion) |
| `cwd` | string | Working directory |
| `timeout` | number | Timeout in ms (default: 600,000) |
| `trust` | boolean | Skip tool confirmations (default: false) |
| `includeTools` | string[] | Allowlist of tools |
| `excludeTools` | string[] | Denylist of tools (takes precedence) |

### Global MCP Settings
```json
{
  "mcp": {
    "allowed": ["server1", "server2"],
    "excluded": ["experimental"],
    "serverCommand": "global-mcp-command"
  }
}
```

## Example Configurations

### Python Stdio
```json
{
  "mcpServers": {
    "mytools": {
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "env": {"DATABASE_URL": "$DB_CONNECTION_STRING"},
      "timeout": 15000
    }
  }
}
```

### Docker-Based
```json
{
  "mcpServers": {
    "dockerized": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "API_KEY", "my-mcp-server:latest"],
      "env": {"API_KEY": "$EXTERNAL_TOKEN"}
    }
  }
}
```

### HTTP with Auth
```json
{
  "mcpServers": {
    "remote": {
      "httpUrl": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer $AUTH_TOKEN"
      }
    }
  }
}
```

## OAuth Support
- Auto-discovers OAuth requirements from 401 responses
- Auth providers: `dynamic_discovery`, `google_credentials`, `service_account_impersonation`
- Tokens stored at `~/.gemini/mcp-oauth-tokens.json`
- Requires browser access (won't work headless/SSH)

## CLI Management
```bash
gemini mcp list                 # List configured servers
gemini mcp add serverName ...   # Add server
gemini mcp remove serverName    # Remove server
gemini mcp enable serverName    # Enable
gemini mcp disable serverName   # Disable
gemini mcp auth serverName      # Authenticate (OAuth)
```

## Usage in Chat
Reference MCP servers with `@` syntax:
```
@shopping-assistant search for wireless mouse under $50
```

## Sources
- https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md
- https://geminicli.com/docs/tools/mcp-server/
- https://audrey.feldroy.com/articles/2025-07-27-Gemini-CLI-Settings-With-MCP
