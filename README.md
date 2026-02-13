# Code Assist Extensions

MCP server that gives AI coding assistants the ability to shop. Works with **Claude Code**, **Codex CLI**, and **Gemini CLI** — one Python server, three agents, via MCP over stdio.

The agent searches Amazon, opens products in a real browser, reads pages, clicks elements, navigates reviews, and manages tabs — all through tool calls. A headed browser lets you watch it work.

## Tools (16)

### Shopping

| Tool | Description |
|------|-------------|
| `search_products` | Search retailers by query. Returns results with URLs and workflow guidance. |
| `compare_prices` | Compare a product across multiple retailers. |
| `get_product_details` | Extract specs, reviews, availability, and pricing from a product page. |
| `open_product_page` | Open a product URL in the headed browser. |
| `add_to_cart` | Add a product to the cart. |
| `preview_checkout` | Show a redacted checkout summary and generate a confirmation code. |
| `confirm_purchase` | Complete purchase with the confirmation code (human-in-the-loop gate). |
| `setup_profile` | Create or update an encrypted shipping/payment profile. |

### Atomic Browsing

The agent pilots the browser directly — it reads a page, decides what to do, calls a tool, reads the result, and repeats.

| Tool | Description |
|------|-------------|
| `read_page` | Extract structured content from the active page: text, buttons, links, inputs, prices. |
| `click_element` | Click an element by description (e.g., "Add to Cart button"). AI resolves to CSS selector. |
| `type_text` | Type into a field by description (e.g., "search box"). |
| `select_option` | Select a dropdown option by description. |
| `scroll_page` | Scroll the page up or down. |
| `go_back` | Browser back button. |
| `open_link` | Open a URL in a new tab, keeping the current page intact. |
| `switch_tab` | Switch between open browser tabs. |

## How It Works

1. You ask the agent to find a product
2. `search_products` searches Amazon via Playwright and returns results with URLs
3. The response includes directive guidance ("DO NOT STOP HERE — open the top products")
4. The agent calls `open_link` to open products in new tabs, `read_page` to read details, `switch_tab` to go back
5. After exploring multiple products, it gives you an informed recommendation
6. If you want to buy, it uses `click_element("Add to Cart")` and walks through checkout with a human-in-the-loop confirmation gate

## Setup

### Prerequisites

- Python 3.10+
- An [OpenRouter](https://openrouter.ai/) API key (for AI element resolution via DeepSeek)

### Install

```bash
git clone https://github.com/Symbiomancer/code-assist-extensions.git
cd code-assist-extensions
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### Environment

```bash
cp .env.example .env
# Edit .env and add your OpenRouter API key:
#   OPENROUTER_API_KEY=sk-or-v1-your-key-here
#   SHOPPING_HEADLESS=false
```

Set `SHOPPING_HEADLESS=true` for headless mode, `false` to watch the browser.

### Configure Your Agent

#### Claude Code

```bash
claude mcp add shopping-assistant -- python -m shopping_tool
```

Or add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "shopping-assistant": {
      "type": "stdio",
      "command": "/path/to/your/.venv/bin/python",
      "args": ["-m", "shopping_tool"]
    }
  }
}
```

#### Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.shopping-assistant]
command = "python"
args = ["-m", "shopping_tool"]
tool_timeout_sec = 120

[mcp_servers.shopping-assistant.env]
OPENROUTER_API_KEY = "your-openrouter-key-here"
SHOPPING_HEADLESS = "false"
```

#### Gemini CLI

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "shopping-assistant": {
      "command": "python",
      "args": ["-m", "shopping_tool"],
      "env": {
        "OPENROUTER_API_KEY": "your-openrouter-key-here",
        "SHOPPING_HEADLESS": "false"
      },
      "timeout": 120000
    }
  }
}
```

### Verify

After configuring, restart your agent and check that the 16 tools are visible. In Claude Code, run `/mcp` to see registered tools.

## Tests

```bash
pytest tests/ -v
```

78 tests covering tool registration, profile encryption, output sanitization, scraper logic, element resolution (fast-path and LLM), and all 16 tool handlers.

## Architecture

```
shopping_tool/
  server.py            # MCP server — 16 tool definitions and handlers
  browser.py           # Playwright lifecycle, tab management, page interaction
  element_resolver.py  # AI selector resolution (fast-path + DeepSeek fallback)
  output_sanitizer.py  # Credit card, SSN, credential redaction
  scrapers/
    base.py            # ProductListing, ProductDetails, BaseRetailerScraper ABC
    amazon.py          # Amazon search + product detail extraction
  actions/
    search.py          # Multi-retailer search orchestrator
  profile/
    schema.py          # Pydantic models for user profile
    crypto.py          # Fernet encryption for profile at rest
    manager.py         # Save/load/redact encrypted profiles
  llm/
    base.py            # LLMProvider ABC
    openrouter.py      # OpenRouter provider (DeepSeek, Grok, Claude, etc.)
```

### Key Design Decisions

**Guided responses** — Every tool response includes directive text that steers the agent's next action. Search results say "DO NOT STOP HERE — open the top products." Product pages say "If you still have products to explore, go back." This keeps the agent in an active browsing loop instead of dumping data and stopping.

**Fast-path element resolution** — Common elements (search box, Add to Cart, quantity selector) resolve instantly via a lookup table. Only unknown elements fall through to DeepSeek. This eliminates unnecessary LLM calls and avoids failures on well-known pages.

**Tab management** — The agent opens products in new tabs and switches back to search results. This preserves context and enables comparison shopping.

**Human-in-the-loop checkout** — `preview_checkout` generates a 6-character confirmation code (5-minute TTL). The agent cannot complete a purchase without the user providing this code back via `confirm_purchase`.

**Encrypted profiles** — Shipping addresses and payment methods are Fernet-encrypted at `~/.config/shopping-assistant/profile.enc`. The AI only sees redacted summaries (city/state, card last 4).

## Roadmap

- **Phase 3**: Cart management, checkout form filling from encrypted profile
- **Phase 4**: Multi-retailer support (Best Buy, Walmart), price comparison via Google Shopping

## License

MIT
