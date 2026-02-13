"""
Shopping Assistant MCP Server.

Exposes 14 tools over stdio for Claude Code, Codex CLI, and Gemini CLI.
Handles product search, cart management, checkout with human-in-the-loop confirmation,
plus atomic browsing tools for interactive page exploration.
"""
import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .output_sanitizer import sanitize_output
from .profile import ProfileManager, UserProfile, ShippingAddress, PaymentMethod
from .browser import BrowserManager
from .actions.search import SearchAction
from . import element_resolver

logger = logging.getLogger(__name__)

# Debug log — records every tool call and response for session review
_DEBUG_LOG_DIR = Path(os.environ.get(
    "SHOPPING_DEBUG_DIR",
    os.path.expanduser("~/.config/shopping-assistant/debug"),
))


def _debug_log(tool_name: str, args: dict, result: str) -> None:
    """Append a tool call entry to the debug log file."""
    try:
        _DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _DEBUG_LOG_DIR / f"session_{datetime.now().strftime('%Y-%m-%d')}.log"
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        entry = (
            f"\n{'='*80}\n"
            f"[{timestamp}] TOOL: {tool_name}\n"
            f"ARGS: {json.dumps(args, indent=2)}\n"
            f"RESPONSE:\n{result}\n"
        )

        with open(log_file, "a") as f:
            f.write(entry)
    except Exception as e:
        logger.debug("Debug log write failed: %s", e)

server = Server("shopping-assistant")

# Lazy-initialized singletons
_profile_manager: ProfileManager | None = None
_browser_manager: BrowserManager | None = None
_search_action: SearchAction | None = None

# Confirmation gate state (in-memory, single-process)
_pending_confirmations: dict[str, dict] = {}

# Confirmation code TTL
_CONFIRMATION_TTL = 300  # 5 minutes


def _get_profile_manager() -> ProfileManager:
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager()
    return _profile_manager


def _get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager


def _get_search_action() -> SearchAction:
    global _search_action
    if _search_action is None:
        _search_action = SearchAction(_get_browser_manager())
    return _search_action


def _generate_confirmation_code() -> str:
    """Generate a 6-character alphanumeric confirmation code."""
    return secrets.token_hex(3).upper()


def _cleanup_expired_confirmations() -> None:
    """Remove expired confirmation codes."""
    now = time.time()
    expired = [k for k, v in _pending_confirmations.items() if now - v["created_at"] > _CONFIRMATION_TTL]
    for k in expired:
        del _pending_confirmations[k]


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_products",
            description="Search for products across retailers by query. Returns product names, prices, ratings, and URLs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Product search query (e.g., 'wireless mouse under $50')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results per retailer (default: no limit)",
                    },
                    "retailers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which retailers to search: 'amazon', 'bestbuy', 'walmart', or 'all'",
                        "default": ["all"],
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="compare_prices",
            description="Compare prices for a specific product across multiple retailers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Product name to compare prices for",
                    },
                    "product_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional specific product URLs to compare",
                    },
                },
                "required": ["product_name"],
            },
        ),
        Tool(
            name="get_product_details",
            description="Get detailed info about a product: specs, reviews summary, availability, and price.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Product page URL",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="open_product_page",
            description="Open a product page in a visible browser window for interactive shopping.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Product page URL to open",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="add_to_cart",
            description="Add a product to the shopping cart. Opens the page if not already open.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Product page URL",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Number of items to add",
                        "default": 1,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="preview_checkout",
            description=(
                "Preview the checkout with your saved profile. Returns a REDACTED summary "
                "(shipping city/state, card last 4 digits, cart total) and a confirmation code. "
                "Does NOT submit payment. The user must provide the confirmation code to proceed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Cart or checkout URL (optional — uses current cart if omitted)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="confirm_purchase",
            description=(
                "Complete the purchase. REQUIRES the confirmation_code returned by preview_checkout. "
                "The user must explicitly provide this code to authorize payment."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "confirmation_code": {
                        "type": "string",
                        "description": "The 6-character code from preview_checkout",
                    },
                },
                "required": ["confirmation_code"],
            },
        ),
        Tool(
            name="setup_profile",
            description=(
                "Create or update your shopping profile (shipping address, payment method). "
                "Data is encrypted at rest and never shown to the AI in full."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["init", "update_shipping", "update_payment", "view_summary"],
                        "description": "What to do: init (full setup), update_shipping, update_payment, or view_summary",
                    },
                    "shipping": {
                        "type": "object",
                        "description": "Shipping address fields (full_name, street, apt, city, state, zip_code, country, phone)",
                    },
                    "payment": {
                        "type": "object",
                        "description": "Payment fields (card_type, card_number, expiry_month, expiry_year, cvv)",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address for order confirmations",
                    },
                },
                "required": ["action"],
            },
        ),
        # --- Atomic browsing tools ---
        Tool(
            name="read_page",
            description=(
                "Read the current browser page. Returns structured content: title, text, "
                "buttons, links, inputs, and prices. Use this to see what's on the page "
                "before deciding what to click or interact with."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="click_element",
            description=(
                "Click a button, link, or interactive element on the current page. "
                "Describe the element in plain English (e.g., 'Add to Cart button', "
                "'See all reviews link', 'first search result'). The system resolves "
                "the description to the correct element using AI."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Human description of what to click (e.g., 'Add to Cart button', 'Next page link')",
                    },
                    "element_type": {
                        "type": "string",
                        "enum": ["button", "link", "input", "any"],
                        "description": "Type hint for the element",
                        "default": "any",
                    },
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="type_text",
            description=(
                "Type text into an input field on the current page. Describe the field "
                "in plain English (e.g., 'search box', 'quantity field', 'email input')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Human description of the input field (e.g., 'search box', 'email field')",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type into the field",
                    },
                },
                "required": ["description", "text"],
            },
        ),
        Tool(
            name="select_option",
            description=(
                "Select an option from a dropdown menu on the current page. "
                "Describe the dropdown and the value to select."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Human description of the dropdown (e.g., 'quantity selector', 'size dropdown')",
                    },
                    "value": {
                        "type": "string",
                        "description": "The option label to select (e.g., '2', 'Large', 'Blue')",
                    },
                },
                "required": ["description", "value"],
            },
        ),
        Tool(
            name="scroll_page",
            description="Scroll the current page up or down to see more content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up"],
                        "description": "Scroll direction",
                        "default": "down",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="go_back",
            description="Go back to the previous page in the browser (like pressing the Back button).",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="open_link",
            description=(
                "Open a URL in a NEW browser tab, keeping the current tab intact. "
                "Use this when you want to explore a link without losing your current page "
                "(e.g., opening a product from search results while keeping the results page)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to open in a new tab",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="switch_tab",
            description=(
                "Switch to a different browser tab by index. "
                "Use this to go back to a previous tab (e.g., search results) "
                "after opening a product in a new tab."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tab_index": {
                        "type": "integer",
                        "description": "The tab index to switch to (shown in read_page output)",
                    },
                },
                "required": ["tab_index"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "setup_profile":
            result = await _handle_setup_profile(arguments)
        elif name == "search_products":
            result = await _handle_search_products(arguments)
        elif name == "compare_prices":
            result = await _handle_compare_prices(arguments)
        elif name == "get_product_details":
            result = await _handle_get_product_details(arguments)
        elif name == "open_product_page":
            result = await _handle_open_product_page(arguments)
        elif name == "add_to_cart":
            result = await _handle_add_to_cart(arguments)
        elif name == "preview_checkout":
            result = await _handle_preview_checkout(arguments)
        elif name == "confirm_purchase":
            result = await _handle_confirm_purchase(arguments)
        elif name == "read_page":
            result = await _handle_read_page(arguments)
        elif name == "click_element":
            result = await _handle_click_element(arguments)
        elif name == "type_text":
            result = await _handle_type_text(arguments)
        elif name == "select_option":
            result = await _handle_select_option(arguments)
        elif name == "scroll_page":
            result = await _handle_scroll_page(arguments)
        elif name == "go_back":
            result = await _handle_go_back(arguments)
        elif name == "open_link":
            result = await _handle_open_link(arguments)
        elif name == "switch_tab":
            result = await _handle_switch_tab(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        if isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, indent=2)
        sanitized = sanitize_output(text)

        _debug_log(name, arguments, sanitized)
        return [TextContent(type="text", text=sanitized)]

    except Exception as e:
        logger.exception("Tool %s failed", name)
        error_text = f"Error: {str(e)}"
        _debug_log(name, arguments, error_text)
        return [TextContent(type="text", text=error_text)]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _handle_setup_profile(args: dict) -> dict:
    """Create, update, or view the encrypted user profile."""
    pm = _get_profile_manager()
    action = args["action"]

    if action == "view_summary":
        if not pm.exists():
            return {"status": "no_profile", "message": "No profile found. Use action='init' to create one."}
        return {"status": "ok", "profile": pm.get_redacted_summary()}

    if action == "init":
        shipping_data = args.get("shipping")
        payment_data = args.get("payment")
        email = args.get("email")
        if not shipping_data or not payment_data or not email:
            return {
                "status": "error",
                "message": "action='init' requires 'shipping', 'payment', and 'email' fields.",
            }
        profile = UserProfile(
            email=email,
            shipping=ShippingAddress(**shipping_data),
            payment=PaymentMethod(**payment_data),
        )
        pm.save(profile)
        return {"status": "saved", "profile": pm.get_redacted_summary()}

    if action == "update_shipping":
        profile = pm.load()
        shipping_data = args.get("shipping")
        if not shipping_data:
            return {"status": "error", "message": "update_shipping requires 'shipping' field."}
        profile.shipping = ShippingAddress(**shipping_data)
        pm.save(profile)
        return {"status": "updated", "profile": pm.get_redacted_summary()}

    if action == "update_payment":
        profile = pm.load()
        payment_data = args.get("payment")
        if not payment_data:
            return {"status": "error", "message": "update_payment requires 'payment' field."}
        profile.payment = PaymentMethod(**payment_data)
        pm.save(profile)
        return {"status": "updated", "profile": pm.get_redacted_summary()}

    return {"status": "error", "message": f"Unknown action: {action}"}


async def _handle_search_products(args: dict) -> str:
    """Search for products across retailers via Playwright. Returns guided text."""
    query = args["query"]
    max_results = args.get("max_results", 50)
    retailers = args.get("retailers", ["all"])

    search = _get_search_action()
    result = await search.search(query, max_results=max_results, retailers=retailers)

    # Format results as readable text with guidance
    lines = [f"Search results for \"{query}\":", ""]

    for i, r in enumerate(result.get("results", []), 1):
        price = r.get("price", "N/A")
        rating = r.get("rating", "No rating")
        lines.append(f"  {i}. {r['title']}")
        lines.append(f"     Price: {price} | Rating: {rating}")
        if r.get("url"):
            lines.append(f"     URL: {r['url']}")
        lines.append("")

    total = result.get("total_results", 0)
    lines.append(f"Found {total} results from: {', '.join(result.get('retailers_searched', []))}")
    lines.append("")

    # Tab info
    tab_header = await _get_tab_header()
    if tab_header:
        lines.append(tab_header)

    # Workflow guidance — directive, not suggestive
    lines.append("=== IMPORTANT: DO NOT STOP HERE ===")
    lines.append("You have search results but NO details yet. You MUST keep calling tools to")
    lines.append("gather product details, reviews, and pricing before responding to the user.")
    lines.append("")
    lines.append("REQUIRED NEXT STEPS:")
    lines.append("  1. Use open_link with the URL of the most promising product to open it in a NEW TAB")
    lines.append("  2. Use read_page to see the full product details, reviews, and pricing")
    lines.append("  3. Use switch_tab(0) to come back to these search results")
    lines.append("  4. Repeat steps 1-3 for the next best products (at least the top 2-3)")
    lines.append("  5. ONLY after you have explored the products, summarize your findings to the user")
    lines.append("")
    lines.append("DO NOT present a table of search results and ask the user what to do.")
    lines.append("Instead, proactively explore the best options and give an informed recommendation.")

    return "\n".join(lines)


async def _handle_compare_prices(args: dict) -> dict:
    """Compare prices across retailers. Stub for Phase 4."""
    return {
        "status": "stub",
        "message": f"Price comparison for '{args['product_name']}'. Coming in Phase 4.",
        "comparison": [],
    }


async def _handle_get_product_details(args: dict) -> dict:
    """Get product details from a URL via Playwright."""
    search = _get_search_action()
    return await search.get_details(args["url"])


async def _handle_open_product_page(args: dict) -> dict:
    """Open a product page in the headed browser."""
    search = _get_search_action()
    return await search.open_page(args["url"])


async def _handle_add_to_cart(args: dict) -> dict:
    """Add product to cart. Stub for Phase 3."""
    return {
        "status": "stub",
        "message": f"Would add {args.get('quantity', 1)}x from {args['url']} to cart. Coming in Phase 3.",
    }


async def _handle_preview_checkout(args: dict) -> dict:
    """Preview checkout with redacted profile and generate confirmation code."""
    pm = _get_profile_manager()
    if not pm.exists():
        return {"status": "error", "message": "No profile found. Use setup_profile first."}

    _cleanup_expired_confirmations()

    code = _generate_confirmation_code()
    _pending_confirmations[code] = {
        "created_at": time.time(),
        "url": args.get("url", "current_cart"),
    }

    summary = pm.get_redacted_summary()

    return {
        "status": "preview",
        "confirmation_code": code,
        "message": (
            f"Review your order details below. To complete the purchase, "
            f"provide the confirmation code: {code}"
        ),
        "shipping_to": summary["shipping"],
        "paying_with": summary["payment"],
        "email": summary["email"],
        "note": "Cart total will be shown once browser checkout is implemented (Phase 3).",
    }


async def _handle_confirm_purchase(args: dict) -> dict:
    """Complete purchase if confirmation code is valid."""
    code = args["confirmation_code"].strip().upper()

    _cleanup_expired_confirmations()

    if code not in _pending_confirmations:
        return {
            "status": "rejected",
            "message": "Invalid or expired confirmation code. Run preview_checkout again.",
        }

    confirmation = _pending_confirmations.pop(code)

    # TODO: Phase 3 — actually submit checkout via Playwright
    return {
        "status": "stub",
        "message": f"Confirmation code {code} accepted. Checkout submission coming in Phase 3.",
        "checkout_url": confirmation["url"],
    }


# ---------------------------------------------------------------------------
# Atomic browsing tool handlers
# ---------------------------------------------------------------------------

async def _get_tab_header() -> str:
    """Generate tab bar header showing all open tabs."""
    browser = _get_browser_manager()
    if browser.tab_count == 0:
        return ""
    tabs = await browser.get_tab_list()
    lines = [f"--- Open Tabs ({len(tabs)}) ---"]
    for t in tabs:
        marker = " >>> ACTIVE" if t["active"] else ""
        lines.append(f"  Tab {t['index']}: \"{t['title']}\" ({t['url']}){marker}")
    lines.append("")
    return "\n".join(lines)


def _format_page_summary(elements: dict, tab_header: str = "") -> str:
    """Format extracted page elements into a readable summary for Claude."""
    lines = []

    if tab_header:
        lines.append(tab_header)

    lines.append(f"Page: \"{elements.get('title', 'Untitled')}\"")
    lines.append(f"URL: {elements.get('url', 'unknown')}")
    lines.append("")

    # Text content
    texts = elements.get("text_content", [])
    if texts:
        lines.append("--- Page Content ---")
        for t in texts:
            lines.append(f"  {t}")
        lines.append("")

    # Buttons
    buttons = elements.get("buttons", [])
    if buttons:
        lines.append(f"--- Buttons ({len(buttons)}) ---")
        for b in buttons:
            label = b.get("text", "(no text)")
            bid = f" id={b['id']}" if b.get("id") else ""
            lines.append(f"  [{b['index']}] \"{label}\"{bid}")
        lines.append("")

    # Links
    links = elements.get("links", [])
    if links:
        lines.append(f"--- Links ({len(links)}) ---")
        for l in links:
            lines.append(f"  [{l['index']}] \"{l['text']}\" -> {l['href']}")
        lines.append("")

    # Inputs
    inputs = elements.get("inputs", [])
    if inputs:
        lines.append(f"--- Input Fields ({len(inputs)}) ---")
        for i in inputs:
            label = i.get("label") or i.get("placeholder") or i.get("name") or "(unlabeled)"
            lines.append(f"  [{i['index']}] {i['type']}: \"{label}\"")
        lines.append("")

    # Selects
    selects = elements.get("selects", [])
    if selects:
        lines.append(f"--- Dropdowns ({len(selects)}) ---")
        for s in selects:
            name = s.get("name") or s.get("id") or "(unnamed)"
            opts = ", ".join(s.get("options", []))
            lines.append(f"  [{s['index']}] \"{name}\": [{opts}]")
        lines.append("")

    return "\n".join(lines)


def _build_guidance(elements: dict) -> str:
    """Generate directive step-by-step guidance that tells Claude to keep going."""
    url = elements.get("url", "")
    buttons = elements.get("buttons", [])
    links = elements.get("links", [])
    inputs = elements.get("inputs", [])
    btn_texts = [b.get("text", "").lower() for b in buttons]
    link_texts = [l.get("text", "").lower() for l in links]

    hints = ["\n=== NEXT STEPS ==="]

    # Detect page type and give directive guidance
    if "amazon.com/s?" in url or "/s?" in url:
        hints.append("You are on a SEARCH RESULTS page. DO NOT stop here.")
        hints.append("")
        hints.append("CONTINUE by exploring the top products:")
        hints.append("  1. Use open_link with a product URL to open it in a NEW TAB")
        hints.append("  2. Use read_page to see the full details")
        hints.append("  3. Use switch_tab(0) to return here and explore the next product")
        hints.append("")
        hints.append("Keep going until you have enough information to give the user a useful answer.")

    elif any("add to cart" in t for t in btn_texts):
        hints.append("You are on a PRODUCT page. Read the details above carefully.")
        hints.append("")
        hints.append("NOW you should:")
        hints.append("  - If the user wants to buy: Use click_element(\"Add to Cart button\")")
        if any("review" in t for t in link_texts + btn_texts):
            hints.append("  - To check reviews: Use scroll_page(\"down\") or click_element(\"See all reviews\")")
        hints.append("  - To compare more products: Use switch_tab(0) to go back and open_link another product")
        hints.append("  - To see more details: Use scroll_page(direction=\"down\")")
        hints.append("")
        hints.append("If you still have products to explore, go back and keep exploring before responding.")

    elif "review" in url.lower() or any("review" in t for t in btn_texts + link_texts):
        hints.append("You are on a REVIEWS page.")
        hints.append("")
        hints.append("CONTINUE reading reviews:")
        hints.append("  1. Scroll down with scroll_page(\"down\") to see more")
        if any("next" in t for t in link_texts + btn_texts):
            hints.append("  2. Use click_element(\"Next page\") then read_page for more reviews")
        hints.append("")
        hints.append("When you have enough info, use switch_tab to go back.")

    elif any("cart" in t.lower() for t in [elements.get("title", "")]):
        hints.append("You are on the CART page.")
        hints.append("")
        hints.append("Next: Use click_element(\"Proceed to checkout button\") then read_page.")

    else:
        hints.append("Continue exploring this page:")
        if inputs:
            hints.append("  - Fill forms: type_text(\"field\", \"value\") then click_element(\"submit\")")
        hints.append("  - Click things: click_element(\"description\") or open_link(url)")
        hints.append("  - See more: scroll_page(\"down\")")
        hints.append("  - Navigate: switch_tab(index) or go_back")

    return "\n".join(hints)


async def _handle_read_page(args: dict) -> str:
    """Read the current browser page content."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    summary = _format_page_summary(elements, tab_header=tab_header)
    guidance = _build_guidance(elements)
    return summary + guidance


async def _handle_click_element(args: dict) -> str:
    """Click an element by description using AI selector resolution."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    description = args["description"]
    element_type = args.get("element_type", "any")

    # Extract page elements for the resolver
    elements = await browser.extract_page_elements(page)

    # Resolve description to CSS selector
    selector = await element_resolver.resolve_selector(
        description=description,
        element_type=element_type,
        page_elements=elements,
    )

    if not selector:
        return (
            f"Could not find element matching: \"{description}\"\n"
            f"Page has {len(elements.get('buttons', []))} buttons and {len(elements.get('links', []))} links.\n"
            "Try using read_page to see what's available, or rephrase your description."
        )

    # Click the element
    success = await browser.click(page, selector)
    if not success:
        return (
            f"Found selector '{selector}' for \"{description}\" but click failed.\n"
            "The element may be obscured or not interactive. Try scroll_page first."
        )

    # Wait for potential navigation
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass

    # Read the updated page
    new_elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    new_summary = _format_page_summary(new_elements, tab_header=tab_header)
    guidance = _build_guidance(new_elements)

    return f"Clicked \"{description}\" (selector: {selector}). Page updated.\n\n{new_summary}{guidance}"


async def _handle_type_text(args: dict) -> str:
    """Type text into a field by description."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    description = args["description"]
    text = args["text"]

    elements = await browser.extract_page_elements(page)
    selector = await element_resolver.resolve_selector(
        description=description,
        element_type="input",
        page_elements=elements,
    )

    if not selector:
        return (
            f"Could not find input field matching: \"{description}\"\n"
            f"Page has {len(elements.get('inputs', []))} input fields.\n"
            "Try using read_page to see available fields."
        )

    success = await browser.fill(page, selector, text)
    if not success:
        return f"Found selector '{selector}' for \"{description}\" but typing failed."

    return f"Typed \"{text}\" into \"{description}\" (selector: {selector})."


async def _handle_select_option(args: dict) -> str:
    """Select a dropdown option by description."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    description = args["description"]
    value = args["value"]

    elements = await browser.extract_page_elements(page)
    selector = await element_resolver.resolve_selector(
        description=description,
        element_type="select",
        page_elements=elements,
    )

    if not selector:
        return (
            f"Could not find dropdown matching: \"{description}\"\n"
            f"Page has {len(elements.get('selects', []))} dropdowns.\n"
            "Try using read_page to see available dropdowns."
        )

    success = await browser.select_option(page, selector, value)
    if not success:
        return f"Found selector '{selector}' for \"{description}\" but selection of \"{value}\" failed."

    return f"Selected \"{value}\" in \"{description}\" (selector: {selector})."


async def _handle_scroll_page(args: dict) -> str:
    """Scroll the current page and return new content."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    direction = args.get("direction", "down")
    await browser.scroll(page, direction)

    elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    summary = _format_page_summary(elements, tab_header=tab_header)
    guidance = _build_guidance(elements)

    return f"Scrolled {direction}.\n\n{summary}{guidance}"


async def _handle_go_back(args: dict) -> str:
    """Navigate back to the previous page."""
    browser = _get_browser_manager()
    page = browser.active_page
    if not page:
        return "No browser page is open. Use open_product_page or search_products first."

    new_url = await browser.go_back(page)

    elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    summary = _format_page_summary(elements, tab_header=tab_header)
    guidance = _build_guidance(elements)

    return f"Navigated back to: {new_url}\n\n{summary}{guidance}"


async def _handle_open_link(args: dict) -> str:
    """Open a URL in a new browser tab, keeping current tab intact."""
    browser = _get_browser_manager()
    url = args["url"]

    page = await browser.open_in_new_tab(url)

    elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    summary = _format_page_summary(elements, tab_header=tab_header)
    guidance = _build_guidance(elements)

    return f"Opened in new tab (Tab {browser.active_tab_index}): {url}\n\n{summary}{guidance}"


async def _handle_switch_tab(args: dict) -> str:
    """Switch to a different browser tab."""
    browser = _get_browser_manager()
    index = args["tab_index"]

    page = browser.switch_tab(index)
    if not page:
        tabs = await browser.get_tab_list()
        tab_info = "\n".join(f"  Tab {t['index']}: {t['title']}" for t in tabs)
        return f"Invalid tab index: {index}. Available tabs:\n{tab_info}"

    elements = await browser.extract_page_elements(page)
    tab_header = await _get_tab_header()
    summary = _format_page_summary(elements, tab_header=tab_header)
    guidance = _build_guidance(elements)

    return f"Switched to Tab {index}.\n\n{summary}{guidance}"


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def main():
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Shopping Assistant MCP server starting...")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        # Clean up browser on shutdown
        if _browser_manager:
            await _browser_manager.close()


def run():
    """Sync entry point for console_scripts."""
    asyncio.run(main())
