"""Tests for MCP server tool registration and dispatch."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from shopping_tool.server import (
    list_tools,
    call_tool,
    _handle_setup_profile,
    _handle_preview_checkout,
    _handle_confirm_purchase,
    _handle_read_page,
    _handle_click_element,
    _handle_type_text,
    _handle_select_option,
    _handle_scroll_page,
    _handle_go_back,
    _handle_open_link,
    _handle_switch_tab,
    _handle_search_products,
    _format_page_summary,
    _build_guidance,
    _pending_confirmations,
    _get_profile_manager,
)
from shopping_tool.profile.manager import ProfileManager
from shopping_tool.profile.crypto import ProfileCrypto
import shopping_tool.server as server_module


EXPECTED_TOOLS = [
    "search_products",
    "compare_prices",
    "get_product_details",
    "open_product_page",
    "add_to_cart",
    "preview_checkout",
    "confirm_purchase",
    "setup_profile",
    "read_page",
    "click_element",
    "type_text",
    "select_option",
    "scroll_page",
    "go_back",
    "open_link",
    "switch_tab",
]


@pytest.mark.asyncio
async def test_list_tools_returns_all_sixteen():
    tools = await list_tools()
    names = [t.name for t in tools]
    assert len(tools) == 16
    for expected in EXPECTED_TOOLS:
        assert expected in names, f"Missing tool: {expected}"


@pytest.mark.asyncio
async def test_all_tools_have_schemas():
    tools = await list_tools()
    for tool in tools:
        assert tool.description, f"{tool.name} missing description"
        assert tool.inputSchema, f"{tool.name} missing inputSchema"
        assert tool.inputSchema["type"] == "object"


@pytest.mark.asyncio
async def test_setup_profile_init(tmp_path):
    pm = ProfileManager(profile_path=tmp_path / "profile.enc")
    pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
    server_module._profile_manager = pm

    result = await _handle_setup_profile({
        "action": "init",
        "email": "test@example.com",
        "shipping": {
            "full_name": "Test User",
            "street": "456 Oak Ave",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97201",
            "phone": "503-555-0100",
        },
        "payment": {
            "card_type": "mastercard",
            "card_number": "5500000000005678",
            "expiry_month": 6,
            "expiry_year": 2028,
            "cvv": "456",
        },
    })

    assert result["status"] == "saved"
    assert result["profile"]["payment"]["last_four"] == "5678"
    # Cleanup
    server_module._profile_manager = None


@pytest.mark.asyncio
async def test_setup_profile_view_no_profile(tmp_path):
    pm = ProfileManager(profile_path=tmp_path / "nope.enc")
    server_module._profile_manager = pm

    result = await _handle_setup_profile({"action": "view_summary"})
    assert result["status"] == "no_profile"
    server_module._profile_manager = None


@pytest.mark.asyncio
async def test_confirmation_code_flow(tmp_path):
    """Test the preview -> confirm flow."""
    # Setup a profile first
    pm = ProfileManager(profile_path=tmp_path / "profile.enc")
    pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
    server_module._profile_manager = pm

    await _handle_setup_profile({
        "action": "init",
        "email": "test@example.com",
        "shipping": {
            "full_name": "Test User",
            "street": "789 Pine",
            "city": "Austin",
            "state": "TX",
            "zip_code": "73301",
            "phone": "512-555-0100",
        },
        "payment": {
            "card_type": "visa",
            "card_number": "4111111111119999",
            "expiry_month": 3,
            "expiry_year": 2029,
            "cvv": "789",
        },
    })

    # Preview
    preview = await _handle_preview_checkout({})
    assert preview["status"] == "preview"
    code = preview["confirmation_code"]
    assert len(code) == 6

    # Confirm with correct code
    confirm = await _handle_confirm_purchase({"confirmation_code": code})
    assert confirm["status"] == "stub"  # Phase 3 will make this real
    assert code not in _pending_confirmations  # Code consumed

    # Confirm again with same code should fail
    confirm2 = await _handle_confirm_purchase({"confirmation_code": code})
    assert confirm2["status"] == "rejected"

    server_module._profile_manager = None


@pytest.mark.asyncio
async def test_confirm_with_bad_code():
    result = await _handle_confirm_purchase({"confirmation_code": "BADCODE"})
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_search_products_returns_guided_text():
    """search_products now returns guided text with workflow instructions."""
    result = await call_tool("search_products", {"query": "laptop"})
    assert len(result) == 1
    text = result[0].text
    # Should contain either results or an error message
    assert "laptop" in text.lower() or "Error" in text


@pytest.mark.asyncio
async def test_unknown_tool():
    result = await call_tool("nonexistent_tool", {})
    assert "Unknown tool" in result[0].text


# ---------------------------------------------------------------------------
# Atomic browsing tool tests
# ---------------------------------------------------------------------------

class TestReadPage:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_read_page({})
        assert "No browser page" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_reads_page_content(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/dp/TEST",
            "title": "Test Product Page",
            "buttons": [{"index": 0, "text": "Add to Cart", "id": "add-to-cart-button", "type": "button", "classes": ""}],
            "links": [{"index": 0, "text": "See all reviews", "href": "https://amazon.com/reviews"}],
            "inputs": [],
            "selects": [],
            "text_content": ["$29.99", "In Stock"],
        })
        mock_browser.tab_count = 1
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/dp/TEST", "title": "Test Product Page", "active": True},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_read_page({})
        assert "Test Product Page" in result
        assert "$29.99" in result
        assert "Add to Cart" in result
        assert "See all reviews" in result
        assert "NEXT STEPS" in result
        server_module._browser_manager = None


class TestClickElement:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_click_element({"description": "button"})
        assert "No browser page" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_selector_not_found(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com",
            "html": "<div>empty</div>",
            "buttons": [],
            "links": [],
        })
        server_module._browser_manager = mock_browser

        with patch("shopping_tool.server.element_resolver") as mock_resolver:
            mock_resolver.resolve_selector = AsyncMock(return_value=None)
            result = await _handle_click_element({"description": "Nonexistent button"})
            assert "Could not find" in result

        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_click_success(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/dp/TEST",
            "html": "<button id='btn'>Click me</button>",
            "title": "After Click",
            "buttons": [{"index": 0, "text": "Click me", "id": "btn", "type": "button", "classes": ""}],
            "links": [],
            "inputs": [],
            "selects": [],
            "text_content": ["Page content after click"],
        })
        mock_browser.click = AsyncMock(return_value=True)
        mock_browser.tab_count = 1
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/dp/TEST", "title": "After Click", "active": True},
        ])
        mock_page.wait_for_load_state = AsyncMock()
        server_module._browser_manager = mock_browser

        with patch("shopping_tool.server.element_resolver") as mock_resolver:
            mock_resolver.resolve_selector = AsyncMock(return_value="#btn")
            result = await _handle_click_element({"description": "Click me button"})
            assert "Clicked" in result
            assert "#btn" in result
            assert "After Click" in result

        server_module._browser_manager = None


class TestTypeText:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_type_text({"description": "search box", "text": "laptop"})
        assert "No browser page" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_type_success(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com",
            "html": "<input id='search' />",
            "inputs": [{"index": 0, "id": "search", "type": "text"}],
        })
        mock_browser.fill = AsyncMock(return_value=True)
        server_module._browser_manager = mock_browser

        with patch("shopping_tool.server.element_resolver") as mock_resolver:
            mock_resolver.resolve_selector = AsyncMock(return_value="#search")
            result = await _handle_type_text({"description": "search box", "text": "wireless mouse"})
            assert "Typed" in result
            assert "wireless mouse" in result

        server_module._browser_manager = None


class TestScrollPage:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_scroll_page({})
        assert "No browser page" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_scroll_down(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.scroll = AsyncMock()
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/dp/TEST",
            "title": "Product Page",
            "buttons": [],
            "links": [],
            "inputs": [],
            "selects": [],
            "text_content": ["More content below"],
        })
        mock_browser.tab_count = 1
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/dp/TEST", "title": "Product Page", "active": True},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_scroll_page({"direction": "down"})
        assert "Scrolled down" in result
        assert "More content below" in result
        mock_browser.scroll.assert_called_once_with(mock_page, "down")
        server_module._browser_manager = None


class TestGoBack:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_go_back({})
        assert "No browser page" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_go_back_success(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.active_page = mock_page
        mock_browser.go_back = AsyncMock(return_value="https://amazon.com/s?k=mouse")
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/s?k=mouse",
            "title": "Search Results",
            "buttons": [],
            "links": [],
            "inputs": [],
            "selects": [],
            "text_content": ["Search results for mouse"],
        })
        mock_browser.tab_count = 1
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/s?k=mouse", "title": "Search Results", "active": True},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_go_back({})
        assert "Navigated back" in result
        assert "Search Results" in result
        server_module._browser_manager = None


class TestSelectOption:
    @pytest.mark.asyncio
    async def test_no_active_page(self):
        server_module._browser_manager = MagicMock()
        server_module._browser_manager.active_page = None
        result = await _handle_select_option({"description": "quantity", "value": "2"})
        assert "No browser page" in result
        server_module._browser_manager = None


class TestOpenLink:
    @pytest.mark.asyncio
    async def test_opens_new_tab(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.open_in_new_tab = AsyncMock(return_value=mock_page)
        mock_browser.active_tab_index = 1
        mock_browser.tab_count = 2
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/dp/TEST",
            "title": "Product Page",
            "buttons": [{"text": "Add to Cart", "index": 0, "id": "", "type": "button", "classes": ""}],
            "links": [],
            "inputs": [],
            "selects": [],
            "text_content": ["$29.99"],
        })
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/s?k=mouse", "title": "Search", "active": False},
            {"index": 1, "url": "https://amazon.com/dp/TEST", "title": "Product Page", "active": True},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_open_link({"url": "https://amazon.com/dp/TEST"})
        assert "new tab" in result.lower() or "Tab 1" in result
        assert "Product Page" in result
        mock_browser.open_in_new_tab.assert_called_once()
        server_module._browser_manager = None


class TestSwitchTab:
    @pytest.mark.asyncio
    async def test_switch_valid_tab(self):
        mock_browser = MagicMock()
        mock_page = AsyncMock()
        mock_browser.switch_tab.return_value = mock_page
        mock_browser.extract_page_elements = AsyncMock(return_value={
            "url": "https://amazon.com/s?k=mouse",
            "title": "Search Results",
            "buttons": [],
            "links": [],
            "inputs": [],
            "selects": [],
            "text_content": ["Results for mouse"],
        })
        mock_browser.tab_count = 2
        mock_browser.active_tab_index = 0
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com/s?k=mouse", "title": "Search Results", "active": True},
            {"index": 1, "url": "https://amazon.com/dp/TEST", "title": "Product", "active": False},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_switch_tab({"tab_index": 0})
        assert "Switched to Tab 0" in result
        assert "Search Results" in result
        server_module._browser_manager = None

    @pytest.mark.asyncio
    async def test_switch_invalid_tab(self):
        mock_browser = MagicMock()
        mock_browser.switch_tab.return_value = None
        mock_browser.get_tab_list = AsyncMock(return_value=[
            {"index": 0, "url": "https://amazon.com", "title": "Amazon", "active": True},
        ])
        server_module._browser_manager = mock_browser

        result = await _handle_switch_tab({"tab_index": 5})
        assert "Invalid tab index" in result
        server_module._browser_manager = None


# ---------------------------------------------------------------------------
# Page summary formatting tests
# ---------------------------------------------------------------------------

class TestFormatPageSummary:
    def test_basic_formatting(self):
        elements = {
            "url": "https://amazon.com/dp/TEST",
            "title": "Test Product",
            "text_content": ["$29.99", "In Stock"],
            "buttons": [{"index": 0, "text": "Add to Cart", "id": "atc", "type": "button", "classes": ""}],
            "links": [{"index": 0, "text": "Reviews", "href": "https://amazon.com/reviews"}],
            "inputs": [{"index": 0, "type": "text", "label": "Quantity", "placeholder": "", "name": "qty"}],
            "selects": [],
        }
        summary = _format_page_summary(elements)
        assert "Test Product" in summary
        assert "$29.99" in summary
        assert "Add to Cart" in summary
        assert "Reviews" in summary
        assert "Quantity" in summary


class TestBuildGuidance:
    def test_search_results_page(self):
        elements = {
            "url": "https://amazon.com/s?k=mouse",
            "buttons": [],
            "links": [],
            "inputs": [],
        }
        guidance = _build_guidance(elements)
        assert "SEARCH RESULTS" in guidance
        assert "DO NOT stop" in guidance
        assert "open_link" in guidance
        assert "switch_tab" in guidance

    def test_product_page_with_cart(self):
        elements = {
            "url": "https://amazon.com/dp/B01234",
            "buttons": [{"text": "Add to Cart"}],
            "links": [{"text": "See all reviews"}],
            "inputs": [],
        }
        guidance = _build_guidance(elements)
        assert "PRODUCT" in guidance
        assert "Add to Cart" in guidance
        assert "review" in guidance.lower()

    def test_reviews_page(self):
        elements = {
            "url": "https://amazon.com/product-reviews/B01234",
            "buttons": [],
            "links": [{"text": "Next page"}],
            "inputs": [],
        }
        guidance = _build_guidance(elements)
        assert "REVIEWS" in guidance
        assert "Next page" in guidance
        assert "switch_tab" in guidance

    def test_search_guidance_has_workflow(self):
        """Verify the search results guidance includes directive multi-step workflow."""
        elements = {
            "url": "https://amazon.com/s?k=laptop",
            "buttons": [],
            "links": [],
            "inputs": [],
        }
        guidance = _build_guidance(elements)
        assert "open_link" in guidance
        assert "read_page" in guidance
        assert "switch_tab" in guidance
        assert "DO NOT stop" in guidance
