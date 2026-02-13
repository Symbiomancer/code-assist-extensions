"""
Amazon scraper — search products and extract details via Playwright.
Uses the shared BrowserManager for all page interactions.
"""
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from ..browser import BrowserManager
from .base import BaseRetailerScraper, ProductListing, ProductDetails

logger = logging.getLogger(__name__)

AMAZON_BASE = "https://www.amazon.com"


class AmazonScraper(BaseRetailerScraper):
    """Amazon product search and detail extraction."""

    retailer_name = "amazon"

    def __init__(self, browser: BrowserManager):
        self._browser = browser

    async def search(self, query: str, max_results: int = 5) -> list[ProductListing]:
        """Search Amazon for products via Playwright."""
        search_url = f"{AMAZON_BASE}/s?k={quote_plus(query)}"
        logger.info("Amazon search: %s", search_url)

        page = await self._browser.new_page(search_url)

        # Wait for search results to load
        try:
            await page.wait_for_selector(
                '[data-component-type="s-search-result"]',
                timeout=10000,
            )
        except Exception:
            logger.warning("Search results selector not found — trying alternate")
            try:
                await page.wait_for_selector(".s-result-item", timeout=5000)
            except Exception:
                logger.error("No search results found on page")
                return []

        # Extract results via JS
        results = await page.evaluate('''
            (maxResults) => {
                const items = document.querySelectorAll('[data-component-type="s-search-result"]');
                const results = [];

                for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                    const item = items[i];

                    // Skip sponsored/ad results that aren't real products
                    const asin = item.getAttribute('data-asin');
                    if (!asin) continue;

                    // Title
                    const titleEl = item.querySelector('h2 a span, h2 span a span, .a-text-normal');
                    const title = titleEl ? titleEl.textContent.trim() : '';
                    if (!title) continue;

                    // URL — try multiple selectors, fall back to ASIN-based URL
                    const linkEl = item.querySelector('h2 a, h2 span a, a.a-link-normal[href*="/dp/"]');
                    let url = linkEl ? linkEl.getAttribute('href') : '';
                    if (url && !url.startsWith('http')) {
                        url = 'https://www.amazon.com' + url;
                    }
                    if (!url && asin) {
                        url = 'https://www.amazon.com/dp/' + asin;
                    }

                    // Price
                    const priceWhole = item.querySelector('.a-price .a-price-whole');
                    const priceFraction = item.querySelector('.a-price .a-price-fraction');
                    let price = null;
                    if (priceWhole) {
                        const whole = priceWhole.textContent.replace(/[^0-9]/g, '');
                        const frac = priceFraction ? priceFraction.textContent.trim() : '00';
                        price = `$${whole}.${frac}`;
                    }

                    // Rating
                    const ratingEl = item.querySelector('.a-icon-alt');
                    const rating = ratingEl ? ratingEl.textContent.trim() : null;

                    // Review count
                    const reviewEl = item.querySelector('[aria-label*="stars"] + span, .a-size-base.s-underline-text');
                    const reviewCount = reviewEl ? reviewEl.textContent.trim().replace(/[()]/g, '') : null;

                    // Image
                    const imgEl = item.querySelector('img.s-image');
                    const imageUrl = imgEl ? imgEl.getAttribute('src') : null;

                    results.push({
                        title: title,
                        price,
                        url,
                        rating,
                        reviewCount,
                        imageUrl,
                        asin,
                    });
                }

                return results;
            }
        ''', max_results)

        listings = []
        for r in results:
            listings.append(ProductListing(
                title=r["title"],
                price=r.get("price"),
                url=r.get("url", ""),
                image_url=r.get("imageUrl"),
                rating=r.get("rating"),
                review_count=r.get("reviewCount"),
                retailer="amazon",
            ))

        logger.info("Amazon search returned %d results for '%s'", len(listings), query)
        return listings

    async def get_details(self, url: str) -> Optional[ProductDetails]:
        """Get full product details from an Amazon product page."""
        logger.info("Amazon details: %s", url)

        # Use existing page or open new one
        page = await self._browser.get_page(url)
        if not page:
            page = await self._browser.new_page(url)

        # Wait for product title — try multiple selectors
        for selector in ["#productTitle", "#title", "h1 span", "h1"]:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                break
            except Exception:
                continue

        details = await page.evaluate('''
            () => {
                const result = {};

                // Title — try multiple selectors
                const titleSelectors = ['#productTitle', '#title span', '#title', 'h1 span.a-text-normal', 'h1'];
                result.title = '';
                for (const sel of titleSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) {
                        result.title = el.textContent.trim();
                        break;
                    }
                }

                // Price — try multiple selectors
                const priceSelectors = [
                    '.a-price .a-offscreen',
                    '#priceblock_ourprice',
                    '#priceblock_dealprice',
                    '.apexPriceToPay .a-offscreen',
                    '#corePrice_feature_div .a-offscreen',
                ];
                result.price = null;
                for (const sel of priceSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) {
                        result.price = el.textContent.trim();
                        break;
                    }
                }

                // Rating
                const ratingEl = document.querySelector('#acrPopover .a-icon-alt, span.a-icon-alt');
                result.rating = ratingEl ? ratingEl.textContent.trim() : null;

                // Review count
                const reviewEl = document.querySelector('#acrCustomerReviewText');
                result.reviewCount = reviewEl ? reviewEl.textContent.trim() : null;

                // Availability
                const availEl = document.querySelector('#availability span');
                result.availability = availEl ? availEl.textContent.trim() : 'Unknown';

                // Feature bullets
                const featureEls = document.querySelectorAll('#feature-bullets ul li span.a-list-item');
                result.features = [];
                featureEls.forEach(el => {
                    const text = el.textContent.trim();
                    if (text && text.length > 5) {
                        result.features.push(text);
                    }
                });

                // Description
                const descEl = document.querySelector('#productDescription p, #productDescription span');
                result.description = descEl ? descEl.textContent.trim() : '';

                // Image
                const imgEl = document.querySelector('#landingImage, #imgBlkFront');
                result.imageUrl = imgEl ? (imgEl.getAttribute('data-old-hires') || imgEl.getAttribute('src')) : null;

                return result;
            }
        ''')

        if not details.get("title"):
            logger.warning("Failed to extract product title from %s", url)
            return None

        return ProductDetails(
            title=details["title"],
            price=details.get("price"),
            url=url,
            description=details.get("description", ""),
            features=details.get("features", []),
            rating=details.get("rating"),
            review_count=details.get("reviewCount"),
            availability=details.get("availability", "Unknown"),
            retailer="amazon",
            image_url=details.get("imageUrl"),
        )
