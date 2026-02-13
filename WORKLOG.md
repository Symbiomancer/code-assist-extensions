# Code Assist Extensions - Work Log

## 2026-02-12

| Time (EST) | Operation |
|---|---|
| 00:07 | Ran 4 explore agents on ~/email-agent to map architecture, tool framework, user data handling, and external service patterns for shopping tool extension design |
| 01:04 | Explored ~/Documents/resume/job-application-agent — mapped web scraping stack (httpx + Playwright), skill-based form filling, Kimi/DeepSeek element resolution, and LLM-driven page interaction patterns |
| 03:30 | Researched extension mechanisms for Claude Code (MCP/stdio), Codex CLI (config.toml), Gemini CLI (settings.json) — all support MCP over stdio |
| 04:00 | Designed implementation plan: 8-tool MCP server, encrypted profiles, Amazon-first, headed browser for demos |
| 15:13 | Phase 1 complete — built shopping_tool MCP server (8 tools, profile encryption, output sanitizer, LLM provider, agent configs, 32 tests all passing) |
| 15:45 | Fixed .mcp.json format (needed "type": "stdio" field) — used `claude mcp add` CLI to register correctly |
| 16:00 | MCP server verified in Claude Code — all 8 tools visible, setup_profile works with encryption + redacted output confirmed |
| 15:50 | Phase 2 complete — built element_resolver.py (DeepSeek e-commerce selector resolution), scrapers/base.py + amazon.py (Playwright search + details), actions/search.py (orchestrator), wired 3 tools to real implementations, 55 tests all passing |
| 17:06 | Added 6 atomic browsing tools (read_page, click_element, type_text, select_option, scroll_page, go_back) — Claude can now interactively browse pages with AI-resolved selectors and guided responses. 14 total tools, 71 tests passing |
| 00:00 | Phase 2.7 — added tab management (open_link, switch_tab), workflow-oriented guidance in all tool responses, search_products returns guided text instead of JSON, debug file logging. 16 total tools, 75 tests passing |
| 00:30 | Fixed 3 critical bugs from live testing: (1) Amazon scraper URLs were empty — added ASIN-based fallback, (2) element resolver failing on all click/type calls — added fast-path known selector lookup bypassing DeepSeek, (3) guidance text too polite — rewrote as directives ("DO NOT STOP HERE", "REQUIRED NEXT STEPS"). 78 tests passing |
| 00:45 | Fixed 2 more live bugs: (1) `read_page` crash on SVG className (SVGAnimatedString has no .substring) — added typeof check, (2) `get_product_details` failing to find title — added multi-selector fallback chain. 78 tests passing |
