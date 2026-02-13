"""Tests for scrapers, search action, and element resolver."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shopping_tool.scrapers.base import ProductListing, ProductDetails, BaseRetailerScraper
from shopping_tool.scrapers.amazon import AmazonScraper
from shopping_tool.actions.search import SearchAction, SCRAPER_CLASSES
from shopping_tool.element_resolver import resolve_selector, _detect_retailer, RETAILER_HINTS
from shopping_tool.browser import BrowserManager


# ---- ProductListing / ProductDetails dataclasses ----

class TestProductModels:
    def test_product_listing_defaults(self):
        listing = ProductListing(title="Test Product")
        assert listing.title == "Test Product"
        assert listing.price is None
        assert listing.retailer == ""
        assert listing.in_stock is True

    def test_product_listing_full(self):
        listing = ProductListing(
            title="Logitech Mouse",
            price="$29.99",
            url="https://amazon.com/dp/B01234",
            rating="4.5 out of 5 stars",
            review_count="1,234",
            retailer="amazon",
        )
        assert listing.price == "$29.99"
        assert listing.retailer == "amazon"

    def test_product_details_to_dict(self):
        details = ProductDetails(
            title="Test Product",
            price="$99.99",
            url="https://amazon.com/dp/B01234",
            description="A great product " * 100,  # Long description
            features=["Feature 1", "Feature 2"] + [f"Feature {i}" for i in range(20)],
            rating="4.2",
            review_count="500",
            availability="In Stock",
            retailer="amazon",
        )
        d = details.to_dict()
        assert d["title"] == "Test Product"
        assert len(d["description"]) == len("A great product " * 100)
        assert len(d["features"]) == 22


# ---- Retailer detection ----

class TestRetailerDetection:
    def test_detect_amazon(self):
        assert _detect_retailer("https://www.amazon.com/dp/B01234") == "amazon"

    def test_detect_amazon_uk(self):
        assert _detect_retailer("https://www.amazon.co.uk/dp/B01234") == "amazon"

    def test_detect_bestbuy(self):
        assert _detect_retailer("https://www.bestbuy.com/product/123") == "bestbuy"

    def test_detect_walmart(self):
        assert _detect_retailer("https://www.walmart.com/ip/123") == "walmart"

    def test_detect_unknown(self):
        assert _detect_retailer("https://www.random-shop.com/item") is None

    def test_retailer_hints_exist(self):
        assert "amazon" in RETAILER_HINTS
        assert "Add to Cart" in RETAILER_HINTS["amazon"]


# ---- Amazon scraper (mocked Playwright) ----

class TestAmazonScraper:
    @pytest.fixture
    def mock_browser(self):
        browser = AsyncMock(spec=BrowserManager)
        return browser

    @pytest.fixture
    def scraper(self, mock_browser):
        return AmazonScraper(mock_browser)

    @pytest.mark.asyncio
    async def test_search_returns_listings(self, scraper, mock_browser):
        """Mock Playwright page to return JS-evaluated results."""
        mock_page = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_page.wait_for_selector = AsyncMock()

        # Simulate JS evaluate returning search results
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "Logitech MX Master 3S",
                "price": "$89.99",
                "url": "https://www.amazon.com/dp/B09HM94VDS",
                "rating": "4.7 out of 5 stars",
                "reviewCount": "12,345",
                "imageUrl": "https://images.amazon.com/test.jpg",
                "asin": "B09HM94VDS",
            },
            {
                "title": "Razer DeathAdder V3",
                "price": "$59.99",
                "url": "https://www.amazon.com/dp/B0BFQX4SYS",
                "rating": "4.5 out of 5 stars",
                "reviewCount": "5,678",
                "imageUrl": None,
                "asin": "B0BFQX4SYS",
            },
        ])

        results = await scraper.search("wireless mouse", max_results=5)

        assert len(results) == 2
        assert results[0].title == "Logitech MX Master 3S"
        assert results[0].price == "$89.99"
        assert results[0].retailer == "amazon"
        assert results[1].title == "Razer DeathAdder V3"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, scraper, mock_browser):
        mock_page = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        mock_page.evaluate = AsyncMock(return_value=[])

        # Second wait_for_selector also fails
        call_count = 0
        async def mock_wait(selector, timeout=None):
            nonlocal call_count
            call_count += 1
            raise Exception("timeout")

        mock_page.wait_for_selector = mock_wait
        results = await scraper.search("nonexistent product xyz")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_details(self, scraper, mock_browser):
        mock_page = AsyncMock()
        mock_browser.get_page.return_value = None
        mock_browser.new_page.return_value = mock_page
        mock_page.wait_for_selector = AsyncMock()

        mock_page.evaluate = AsyncMock(return_value={
            "title": "Logitech MX Master 3S",
            "price": "$89.99",
            "rating": "4.7 out of 5 stars",
            "reviewCount": "12,345 ratings",
            "availability": "In Stock",
            "features": ["Ergonomic design", "USB-C charging", "8K DPI sensor"],
            "description": "Advanced wireless mouse for productivity",
            "imageUrl": "https://images.amazon.com/test.jpg",
        })

        details = await scraper.get_details("https://www.amazon.com/dp/B09HM94VDS")

        assert details is not None
        assert details.title == "Logitech MX Master 3S"
        assert details.price == "$89.99"
        assert details.retailer == "amazon"
        assert len(details.features) == 3

    @pytest.mark.asyncio
    async def test_get_details_no_title(self, scraper, mock_browser):
        mock_page = AsyncMock()
        mock_browser.get_page.return_value = mock_page
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={"title": "", "price": None})

        details = await scraper.get_details("https://www.amazon.com/dp/BAD")
        assert details is None


# ---- SearchAction ----

class TestSearchAction:
    @pytest.fixture
    def mock_browser(self):
        return AsyncMock(spec=BrowserManager)

    @pytest.fixture
    def action(self, mock_browser):
        return SearchAction(mock_browser)

    def test_detect_retailer_amazon(self, action):
        assert action._detect_retailer("https://www.amazon.com/dp/B01234") == "amazon"

    def test_detect_retailer_unknown(self, action):
        assert action._detect_retailer("https://shop.example.com/item") is None

    @pytest.mark.asyncio
    async def test_search_wires_to_scraper(self, action, mock_browser):
        mock_page = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "Test Mouse",
                "price": "$25.00",
                "url": "https://amazon.com/dp/TEST",
                "rating": "4.0",
                "reviewCount": "100",
                "imageUrl": None,
                "asin": "TEST123",
            },
        ])

        result = await action.search("mouse", max_results=3, retailers=["amazon"])

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert result["results"][0]["title"] == "Test Mouse"
        assert "amazon" in result["retailers_searched"]

    @pytest.mark.asyncio
    async def test_search_unsupported_retailer(self, action):
        result = await action.search("mouse", retailers=["target"])
        assert result["status"] == "ok"
        assert result["total_results"] == 0

    @pytest.mark.asyncio
    async def test_get_details_unsupported_url(self, action):
        result = await action.get_details("https://shop.example.com/item")
        assert result["status"] == "error"
        assert "Unsupported" in result["message"]

    @pytest.mark.asyncio
    async def test_open_page(self, action, mock_browser):
        mock_page = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_browser.extract_page_elements.return_value = {
            "url": "https://amazon.com/dp/TEST",
            "title": "Test Product",
            "buttons": [{"text": "Add to Cart"}],
            "inputs": [],
            "text_content": ["$29.99"],
        }

        result = await action.open_page("https://amazon.com/dp/TEST")
        assert result["status"] == "ok"
        assert result["title"] == "Test Product"
        assert result["buttons_found"] == 1


# ---- Element resolver (mocked LLM) ----

class TestElementResolver:
    @pytest.mark.asyncio
    async def test_fast_resolve_search_box(self):
        """Known selectors should resolve instantly without calling LLM."""
        result = await resolve_selector(
            description="search box",
            element_type="input",
            page_elements={"html": "<input id='twotabsearchtextbox'>", "url": "https://www.amazon.com/s?k=test"},
        )
        assert result == "#twotabsearchtextbox"

    @pytest.mark.asyncio
    async def test_fast_resolve_add_to_cart(self):
        """'Add to Cart' on Amazon should resolve without LLM."""
        result = await resolve_selector(
            description="Add to Cart",
            element_type="button",
            page_elements={"html": "<button>Add to Cart</button>", "url": "https://amazon.com/dp/B01234"},
        )
        assert result == "#add-to-cart-button"

    @pytest.mark.asyncio
    async def test_fast_resolve_unknown_description_falls_through(self):
        """Unknown descriptions should fall through to LLM."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "selector": ".custom-widget",
            "found": True,
            "reason": "Matched by class",
        })

        with patch("shopping_tool.element_resolver.get_provider") as mock_get:
            provider = AsyncMock()
            provider.run.return_value = mock_response
            mock_get.return_value = provider

            result = await resolve_selector(
                description="custom widget button",
                element_type="button",
                page_elements={"html": "<button class='custom-widget'>Click</button>", "url": "https://amazon.com"},
            )
            assert result == ".custom-widget"
            # Verify LLM was actually called (not fast-resolved)
            provider.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_selector_success(self):
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "selector": "#special-btn",
            "found": True,
            "reason": "Button has unique ID",
        })

        with patch("shopping_tool.element_resolver.get_provider") as mock_get:
            provider = AsyncMock()
            provider.run.return_value = mock_response
            mock_get.return_value = provider

            result = await resolve_selector(
                description="special checkout button",
                element_type="button",
                page_elements={"html": "<button id='special-btn'>Checkout</button>", "url": "https://amazon.com"},
            )

            assert result == "#special-btn"

    @pytest.mark.asyncio
    async def test_resolve_selector_not_found(self):
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "selector": "",
            "found": False,
            "reason": "No matching element",
        })

        with patch("shopping_tool.element_resolver.get_provider") as mock_get:
            provider = AsyncMock()
            provider.run.return_value = mock_response
            mock_get.return_value = provider

            result = await resolve_selector(
                description="Nonexistent button",
                element_type="button",
                page_elements={"html": "<div>No buttons here</div>", "url": "https://amazon.com"},
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_resolve_selector_no_api_key(self):
        with patch("shopping_tool.element_resolver.get_provider", side_effect=ValueError("OPENROUTER_API_KEY not set")):
            result = await resolve_selector(
                description="test",
                element_type="button",
                page_elements={"html": "<div></div>"},
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_resolve_selector_json_in_fences(self):
        mock_response = MagicMock()
        mock_response.content = '```json\n{"selector": ".buy-btn", "found": true, "reason": "class match"}\n```'

        with patch("shopping_tool.element_resolver.get_provider") as mock_get:
            provider = AsyncMock()
            provider.run.return_value = mock_response
            mock_get.return_value = provider

            result = await resolve_selector(
                description="Buy button",
                element_type="button",
                page_elements={"html": "<button class='buy-btn'>Buy</button>", "url": "https://amazon.com"},
            )

            assert result == ".buy-btn"
