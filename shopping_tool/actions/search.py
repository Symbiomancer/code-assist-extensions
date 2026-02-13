"""Search action — orchestrates product searches across retailers."""
import logging
from typing import Optional

from ..browser import BrowserManager
from ..scrapers.base import BaseRetailerScraper, ProductListing, ProductDetails
from ..scrapers.amazon import AmazonScraper

logger = logging.getLogger(__name__)

# Registry of available scrapers
SCRAPER_CLASSES = {
    "amazon": AmazonScraper,
}


class SearchAction:
    """Orchestrates product search and detail retrieval across retailers."""

    def __init__(self, browser: BrowserManager):
        self._browser = browser
        self._scrapers: dict[str, BaseRetailerScraper] = {}

    def _get_scraper(self, retailer: str) -> Optional[BaseRetailerScraper]:
        """Get or create a scraper instance for a retailer."""
        if retailer not in self._scrapers:
            cls = SCRAPER_CLASSES.get(retailer)
            if cls is None:
                logger.warning("No scraper for retailer: %s", retailer)
                return None
            self._scrapers[retailer] = cls(self._browser)
        return self._scrapers[retailer]

    async def search(
        self,
        query: str,
        max_results: int = 5,
        retailers: list[str] | None = None,
    ) -> dict:
        """
        Search for products across retailers.

        Returns dict with:
            - status: "ok" or "error"
            - query: the search query
            - results: list of product dicts
            - retailers_searched: list of retailers
        """
        if not retailers or "all" in retailers:
            retailers = list(SCRAPER_CLASSES.keys())

        all_results: list[dict] = []
        retailers_searched: list[str] = []

        for retailer in retailers:
            scraper = self._get_scraper(retailer)
            if scraper is None:
                continue

            try:
                listings = await scraper.search(query, max_results=max_results)
                retailers_searched.append(retailer)

                for listing in listings:
                    all_results.append({
                        "title": listing.title,
                        "price": listing.price,
                        "url": listing.url,
                        "rating": listing.rating,
                        "review_count": listing.review_count,
                        "retailer": listing.retailer,
                        "in_stock": listing.in_stock,
                    })

            except Exception as e:
                logger.error("Search failed for %s: %s", retailer, e)
                retailers_searched.append(f"{retailer} (error)")

        return {
            "status": "ok",
            "query": query,
            "results": all_results,
            "retailers_searched": retailers_searched,
            "total_results": len(all_results),
        }

    async def get_details(self, url: str) -> dict:
        """
        Get product details from a URL.
        Auto-detects retailer from URL.
        """
        retailer = self._detect_retailer(url)
        if not retailer:
            return {
                "status": "error",
                "message": f"Unsupported retailer URL: {url}. Supported: {list(SCRAPER_CLASSES.keys())}",
            }

        scraper = self._get_scraper(retailer)
        if not scraper:
            return {"status": "error", "message": f"No scraper for: {retailer}"}

        try:
            details = await scraper.get_details(url)
            if details is None:
                return {"status": "error", "message": "Could not extract product details from page."}
            return {"status": "ok", "details": details.to_dict()}

        except Exception as e:
            logger.error("Get details failed for %s: %s", url, e)
            return {"status": "error", "message": str(e)}

    async def open_page(self, url: str) -> dict:
        """Open a product page in the browser."""
        try:
            page = await self._browser.new_page(url)
            elements = await self._browser.extract_page_elements(page)
            return {
                "status": "ok",
                "url": elements.get("url", url),
                "title": elements.get("title", ""),
                "buttons_found": len(elements.get("buttons", [])),
                "inputs_found": len(elements.get("inputs", [])),
                "text_content": elements.get("text_content", [])[:10],
            }
        except Exception as e:
            logger.error("Open page failed for %s: %s", url, e)
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _detect_retailer(url: str) -> Optional[str]:
        """Detect retailer from URL."""
        url_lower = url.lower()
        for retailer in SCRAPER_CLASSES:
            if retailer in url_lower:
                return retailer
        return None
