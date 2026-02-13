# Claude Code MCP Extension Mechanism

## Overview
Claude Code supports extensions via MCP (Model Context Protocol) servers. These are external processes that expose tools, resources, and prompts through a standardized JSON-RPC 2.0 protocol.

## Transport Types
- **stdio** (recommended for local): spawns subprocess, communicates via stdin/stdout
- **http**: remote server with HTTP streaming
- **sse** (deprecated): Server-Sent Events

## Configuration Locations
- **Project scope**: `.mcp.json` at project root (shared via version control)
- **User scope**: `~/.claude.json` (private, all projects)
- **Managed**: `/etc/claude-code/managed-mcp.json` (admin-controlled)

## Adding Servers

### CLI Method
```bash
claude mcp add --transport stdio shopping-assistant -- python -m shopping_tool
claude mcp add --transport stdio shopping-assistant --env API_KEY=value -- python server.py
```

### Config File (.mcp.json)
```json
{
  "mcpServers": {
    "shopping-assistant": {
      "command": "python",
      "args": ["-m", "shopping_tool"],
      "env": {
        "OPENROUTER_API_KEY": "${OPENROUTER_API_KEY}"
      }
    }
  }
}
```

## Environment Variable Expansion
- `${VAR}` — required, fails if not set
- `${VAR:-default}` — with fallback

## MCP Server Protocol

### Tool Discovery (tools/list)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
```

### Tool Definition Format
```json
{
  "name": "search_products",
  "description": "Search for products by query",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Search query"}
    },
    "required": ["query"]
  }
}
```

### Tool Invocation (tools/call)
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "search_products",
    "arguments": {"query": "laptop under $1000"}
  }
}
```

### Tool Result
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {"type": "text", "text": "Found 5 laptops..."}
    ],
    "isError": false
  }
}
```

## Python SDK Pattern
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("server-name")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name="...", description="...", inputSchema={...})]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text="result")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
```

## Management Commands
```bash
claude mcp list              # List configured servers
claude mcp get <name>        # Get server details
claude mcp remove <name>     # Remove server
/mcp                         # Check status within Claude Code
```

## Advanced Features
- **MCP Tool Search**: Auto-enabled when tool descriptions exceed 10% context; loads tools on-demand
- **Resources**: `@server://resource/path` to reference server-provided files/data
- **Prompts as Commands**: Servers can expose prompts as `/mcp__servername__promptname`
- **Dynamic Updates**: `notifications/tools/list_changed` refreshes tool list

## Sources
- https://code.claude.com/docs/en/mcp
- https://modelcontextprotocol.io/specification/2025-11-25
- https://github.com/modelcontextprotocol/python-sdk
