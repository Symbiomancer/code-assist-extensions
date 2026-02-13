# Shopping Assistant MCP Extension

**Date**: 2026-02-12
**Status**: Phase 2 Complete

## Overview
MCP server providing shopping tools for Claude Code, Codex CLI, and Gemini CLI.
Single Python server works with all three agents via MCP over stdio.

## Tools (16 total)

### Shopping Tools
1. `search_products` — search retailers by query (returns workflow-guided text)
2. `compare_prices` — compare across retailers
3. `get_product_details` — specs, reviews, availability
4. `open_product_page` — open in headed browser
5. `add_to_cart` — add product to cart
6. `preview_checkout` — redacted summary + confirmation code
7. `confirm_purchase` — submit with code (human-in-the-loop)
8. `setup_profile` — encrypted shipping/payment profile

### Atomic Browsing Tools (Claude pilots the browser)
9. `read_page` — read current page content (text, buttons, links, inputs)
10. `click_element` — click by description, AI-resolved to CSS selector
11. `type_text` — type into field by description
12. `select_option` — select dropdown by description
13. `scroll_page` — scroll up/down to see more content
14. `go_back` — browser back button
15. `open_link` — open URL in a new tab (preserves current page)
16. `switch_tab` — switch between open browser tabs

## Architecture
- MCP server: `mcp.server.Server` with stdio transport
- Profile: Fernet-encrypted at `~/.config/shopping-assistant/profile.enc`
- LLM: DeepSeek via OpenRouter for element resolution
- Browser: Playwright (headed mode for demos)
- Sanitizer: PII/card/credential redaction on all outputs

## Phase 1 (Complete)
- Project scaffolding, pyproject.toml
- LLM provider (OpenRouter)
- Encrypted profile system (Fernet + Pydantic)
- Output sanitizer (credit cards, SSN, credentials)
- MCP server with all 8 tools (stubs for browser-dependent tools)
- Agent configs for Claude Code, Codex CLI, Gemini CLI
- Test suite (sanitizer, crypto, server)

## Phase 2 (Complete)
- Browser automation (Playwright BrowserManager) — lifecycle, click/fill/select, page element extraction
- LLM element resolver (DeepSeek via OpenRouter) — retailer URL detection, Amazon/BestBuy/Walmart selector hints
- Scrapers: BaseRetailerScraper ABC + AmazonScraper (Playwright search + product details via JS evaluation)
- SearchAction orchestrator — multi-retailer search, auto-detect retailer from URL
- Wired `search_products`, `get_product_details`, `open_product_page` to real implementations
- 55 tests passing (23 new for scrapers, element resolver, search action)

## Phase 2.5 (Complete) — Atomic Browsing Tools
- 6 new tools: read_page, click_element, type_text, select_option, scroll_page, go_back
- Active page concept — BrowserManager tracks which page Claude is looking at
- AI selector resolution — click_element/type_text describe elements in English, DeepSeek resolves to CSS selectors
- Guided responses — each tool returns contextual hints (page type detection, available actions)
- Enhanced page extraction — links, richer text content, review elements, deduplication
- 71 tests passing (16 new for atomic tools, formatting, guidance)

## Phase 2.7 (Complete) — Tab Management & Workflow Guidance
- 2 new tools: open_link (new tab), switch_tab (switch between tabs)
- BrowserManager refactored to list-based tab tracking with active_tab_index
- Workflow-oriented guidance — all tool responses include step-by-step NEXT STEPS instructions
- search_products returns guided text (not JSON) with workflow for exploring results
- Tab header in all responses shows open tabs with active marker
- Debug file logging — every tool call written to ~/.config/shopping-assistant/debug/
- 75 tests passing

## Phase 3
- Cart management (add to cart flow)
- Checkout form filling from encrypted profile
- Wire add_to_cart, preview_checkout, confirm_purchase

## Phase 4
- Multi-retailer (Best Buy, Walmart)
- Price comparison (Google Shopping)
- README with demos for all three agents
