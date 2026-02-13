"""
DeepSeek-based element resolver for e-commerce pages.
Adapted from job-application-agent's kimi_resolver.py.
Uses DeepSeek via OpenRouter to resolve human descriptions to CSS selectors.
"""
import asyncio
import json
import logging
import time
from typing import Optional

from .llm.openrouter import get_provider

logger = logging.getLogger(__name__)

# Retailer detection patterns
RETAILER_URL_PATTERNS = {
    "amazon": ["amazon.com", "amazon.co.uk", "amazon.ca"],
    "bestbuy": ["bestbuy.com"],
    "walmart": ["walmart.com"],
    "target": ["target.com"],
    "newegg": ["newegg.com"],
    "ebay": ["ebay.com"],
}

# Retailer-specific selector hints for the LLM
RETAILER_HINTS = {
    "amazon": """
## AMAZON-SPECIFIC PATTERNS
- Add to Cart: #add-to-cart-button, input[name="submit.add-to-cart"]
- Buy Now: #buy-now-button, input[name="submit.buy-now"]
- Product title: #productTitle, span#productTitle
- Price: .a-price .a-offscreen, span.a-price-whole, #priceblock_ourprice
- Quantity: select#quantity, #quantity
- Search box: #twotabsearchtextbox
- Search button: input#nav-search-submit-button
- Search results: div[data-component-type="s-search-result"]
- Star rating: span.a-icon-alt (text like "4.5 out of 5 stars")
- Review count: #acrCustomerReviewText
- Availability: #availability span
- Delivery info: #deliveryBlockMessage, .delivery-message
- Variant selectors: #variation_color_name li, #variation_size_name li
""",
    "bestbuy": """
## BEST BUY-SPECIFIC PATTERNS
- Add to Cart: button.add-to-cart-button, [data-button-state="ADD_TO_CART"]
- Price: div.priceView-hero-price span, .pricing-price__regular-price
- Product title: h1.heading-5, div.sku-title h1
- Search: input#gh-search-input
""",
    "walmart": """
## WALMART-SPECIFIC PATTERNS
- Add to Cart: button[data-testid="add-to-cart-button"], button:has-text("Add to cart")
- Price: span[data-testid="price-wrap"], .price-characteristic
- Product title: h1[itemprop="name"]
- Search: input[type="search"], #global-search-input
""",
}


def _detect_retailer(url: str) -> Optional[str]:
    """Detect retailer from URL."""
    url_lower = url.lower()
    for retailer, patterns in RETAILER_URL_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return retailer
    return None


# Fast-path: keyword → CSS selector for common elements (no LLM needed)
KNOWN_SELECTORS: dict[str, dict[str, str]] = {
    "amazon": {
        "search box": "#twotabsearchtextbox",
        "search field": "#twotabsearchtextbox",
        "search input": "#twotabsearchtextbox",
        "search bar": "#twotabsearchtextbox",
        "search amazon": "#twotabsearchtextbox",
        "search button": "#nav-search-submit-button",
        "submit search": "#nav-search-submit-button",
        "add to cart": "#add-to-cart-button",
        "add to cart button": "#add-to-cart-button",
        "buy now": "#buy-now-button",
        "buy now button": "#buy-now-button",
        "quantity": "select#quantity",
        "quantity selector": "select#quantity",
        "quantity dropdown": "select#quantity",
        "see all reviews": 'a[data-hook="see-all-reviews-link-foot"]',
        "all reviews": 'a[data-hook="see-all-reviews-link-foot"]',
        "reviews link": 'a[data-hook="see-all-reviews-link-foot"]',
        "next page": "ul.a-pagination li.a-last a",
        "next": "ul.a-pagination li.a-last a",
    },
    "bestbuy": {
        "search box": "#gh-search-input",
        "search field": "#gh-search-input",
        "add to cart": "button.add-to-cart-button",
        "add to cart button": "button.add-to-cart-button",
    },
    "walmart": {
        "search box": 'input[type="search"]',
        "search field": 'input[type="search"]',
        "add to cart": 'button[data-testid="add-to-cart-button"]',
        "add to cart button": 'button[data-testid="add-to-cart-button"]',
    },
}


def _fast_resolve(description: str, url: str) -> Optional[str]:
    """Try to resolve a description to a known selector without calling the LLM."""
    retailer = _detect_retailer(url)
    if not retailer or retailer not in KNOWN_SELECTORS:
        return None
    desc_lower = description.lower().strip()
    return KNOWN_SELECTORS[retailer].get(desc_lower)


async def resolve_selector(
    description: str,
    element_type: str,
    page_elements: dict,
    model: str = "deepseek",
) -> Optional[str]:
    """
    Use DeepSeek to resolve a human description to a CSS selector.

    Args:
        description: Human-readable description like "Add to Cart button"
        element_type: One of "button", "input", "select", "link"
        page_elements: Dict from BrowserManager.extract_page_elements() with 'html' key
        model: LLM model shortcut (default: "deepseek")

    Returns:
        CSS selector string for Playwright, or None if not found
    """
    # Fast-path: check known selectors first (no LLM call needed)
    url = page_elements.get("url", "")
    fast_result = _fast_resolve(description, url)
    if fast_result:
        logger.info("Fast-resolved '%s' -> %s", description, fast_result)
        return fast_result

    system = """You resolve element descriptions to CSS selectors for browser automation on e-commerce websites.

## OUTPUT FORMAT
Return ONLY a JSON object:
- "selector": a valid CSS selector
- "found": true if element was found, false if not
- "reason": brief explanation

## SELECTOR STRATEGIES (in order of preference)
1. Use unique id: #add-to-cart-button
2. Use data-testid: [data-testid="add-to-cart"]
3. Use specific class + tag: button.add-to-cart-btn
4. Use aria-label: [aria-label="Add to Cart"]
5. Use name attribute: input[name="quantity"]
6. Use text content: button:has-text("Add to Cart")
7. Combine attributes: button[type="submit"][class*="cart"]

## CRITICAL RULES
1. Prefer IDs and data-testid attributes — they're most stable
2. For forms, look for elements inside <form> tags first
3. Avoid selectors that match multiple elements — be specific
4. If an element has a unique ID, use it (e.g., #add-to-cart-button)
5. For price elements, prefer .a-offscreen or the innermost span containing the value
6. Return ONLY the JSON object, no other text"""

    # Add retailer-specific hints
    retailer = _detect_retailer(url)
    hints = RETAILER_HINTS.get(retailer, "")
    if hints:
        system += hints

    # Get HTML, truncate if needed
    page_html = page_elements.get("html", "")
    max_length = 100_000
    if len(page_html) > max_length:
        body_start = page_html.find("<body")
        if body_start > 0:
            page_html = page_html[body_start : body_start + max_length]
        else:
            page_html = page_html[:max_length]
        page_html += "\n<!-- HTML truncated -->"

    prompt = f"""Find the element matching this description:
"{description}"

Element type hint: {element_type}

PAGE HTML:
```html
{page_html}
```

Return JSON with selector, found, and reason."""

    try:
        provider = get_provider(model=model)
    except ValueError:
        logger.error("OPENROUTER_API_KEY not set — cannot resolve selectors")
        return None

    logger.info("Resolving '%s' (type=%s, html=%d chars)", description, element_type, len(page_html))
    start = time.time()

    for attempt in range(3):
        try:
            response = await asyncio.wait_for(
                provider.run(prompt, system=system, max_tokens=500),
                timeout=60.0,
            )
            content = response.content
            logger.debug("DeepSeek response in %.1fs: %s", time.time() - start, content[:200])

            if not content:
                if attempt < 2:
                    await asyncio.sleep((attempt + 1) * 2)
                    continue
                logger.warning("Empty response after 3 attempts")
                return None

            # Extract JSON from markdown fences if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip())

            if data.get("found", False):
                selector = data.get("selector", "")
                logger.info("Resolved '%s' -> %s (%s)", description, selector, data.get("reason", ""))
                return selector
            else:
                logger.info("Element not found: '%s' — %s", description, data.get("reason", ""))
                return None

        except asyncio.TimeoutError:
            if attempt < 2:
                logger.warning("Timeout (attempt %d/3) — retrying", attempt + 1)
                continue
            logger.error("Timeout after 3 attempts (%.1fs)", time.time() - start)
            return None
        except json.JSONDecodeError as e:
            if attempt < 2:
                logger.warning("JSON parse error (attempt %d/3): %s — retrying", attempt + 1, e)
                await asyncio.sleep((attempt + 1) * 2)
                continue
            logger.error("JSON parse error after 3 attempts: %s", e)
            return None
        except Exception as e:
            if attempt < 2:
                logger.warning("Error (attempt %d/3): %s — retrying", attempt + 1, e)
                await asyncio.sleep((attempt + 1) * 2)
                continue
            logger.error("Resolver failed after 3 attempts: %s", e)
            return None

    return None
