"""
Browser manager — Playwright lifecycle, page interactions, and element extraction.

Adapted from job-application-agent's BaseScraper and SkillContext.
Single browser instance shared across all tool calls.
"""
import asyncio
import logging
import os
import random
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages a single Playwright browser instance across MCP tool calls."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._tabs: list[Page] = []  # ordered list of open tabs
        self._active_tab_index: int = -1

    @property
    def active_page(self) -> Optional[Page]:
        """The page Claude is currently looking at."""
        if 0 <= self._active_tab_index < len(self._tabs):
            return self._tabs[self._active_tab_index]
        return None

    @property
    def tab_count(self) -> int:
        return len(self._tabs)

    @property
    def active_tab_index(self) -> int:
        return self._active_tab_index

    @property
    def headless(self) -> bool:
        return os.environ.get("SHOPPING_HEADLESS", "false").lower() == "true"

    async def _ensure_browser(self) -> Browser:
        """Launch browser if not already running."""
        if self._browser and self._browser.is_connected():
            return self._browser

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        logger.info("Browser launched (headless=%s)", self.headless)
        return self._browser

    async def _ensure_context(self) -> BrowserContext:
        """Get or create a browser context with realistic settings."""
        if self._context:
            return self._context

        browser = await self._ensure_browser()
        self._context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        return self._context

    async def new_page(self, url: str) -> Page:
        """Open a URL in a new tab and make it active."""
        context = await self._ensure_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._random_delay(500, 1500)
        self._tabs.append(page)
        self._active_tab_index = len(self._tabs) - 1
        logger.info("Opened tab %d: %s", self._active_tab_index, url)
        return page

    async def open_in_new_tab(self, url: str) -> Page:
        """Open a URL in a new tab without closing the current one."""
        return await self.new_page(url)

    def switch_tab(self, index: int) -> Optional[Page]:
        """Switch to a tab by index. Returns the page or None if invalid."""
        if 0 <= index < len(self._tabs):
            self._active_tab_index = index
            logger.info("Switched to tab %d: %s", index, self._tabs[index].url)
            return self._tabs[index]
        logger.warning("Invalid tab index: %d (have %d tabs)", index, len(self._tabs))
        return None

    async def get_tab_list(self) -> list[dict]:
        """Return info about all open tabs."""
        tabs = []
        for i, page in enumerate(self._tabs):
            try:
                url = page.url
                title = await page.title()
            except Exception:
                url = "(closed)"
                title = "(closed)"
            tabs.append({
                "index": i,
                "url": url,
                "title": title,
                "active": i == self._active_tab_index,
            })
        return tabs

    async def get_page(self, url: str) -> Optional[Page]:
        """Get an existing page by URL, or None."""
        for page in self._tabs:
            try:
                if page.url == url:
                    return page
            except Exception:
                continue
        return None

    async def extract_page_elements(self, page: Page) -> dict:
        """
        Extract interactive elements from page via JS evaluation.
        Adapted from job-application-agent skill_executor._extract_page_elements().
        """
        page_html = await page.content()

        elements = await page.evaluate('''
            () => {
                const result = {
                    url: window.location.href,
                    title: document.title,
                    buttons: [],
                    inputs: [],
                    selects: [],
                    links: [],
                    text_content: [],
                };

                // Buttons and clickable elements
                const buttonSelectors = 'button, input[type="submit"], input[type="button"], [role="button"], a[onclick], a[class*="button"], a[class*="btn"], a[class*="add-to-cart"], [data-testid*="add-to-cart"], [id*="add-to-cart"]';
                const buttons = document.querySelectorAll(buttonSelectors);
                let btnIndex = 0;
                buttons.forEach(btn => {
                    if (btn.offsetParent === null) return;
                    const text = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                    result.buttons.push({
                        index: btnIndex++,
                        text: text,
                        type: btn.tagName.toLowerCase(),
                        id: btn.id || null,
                        classes: (typeof btn.className === 'string' ? btn.className : ''),
                    });
                });

                // Input fields
                const inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea');
                let inputIndex = 0;
                inputs.forEach(input => {
                    if (input.offsetParent !== null) {
                        let label = '';
                        const labelEl = document.querySelector(`label[for="${input.id}"]`);
                        if (labelEl) {
                            label = labelEl.innerText.trim();
                        } else {
                            const parent = input.closest('label, .form-group, .field');
                            if (parent) {
                                const labelText = parent.querySelector('label, .label, span');
                                if (labelText) label = labelText.innerText.trim();
                            }
                        }
                        result.inputs.push({
                            index: inputIndex++,
                            id: input.id || '',
                            type: input.type || 'text',
                            name: input.name || '',
                            label: label,
                            placeholder: (input.placeholder || ''),
                            required: input.required,
                        });
                    }
                });

                // Select dropdowns
                const selects = document.querySelectorAll('select');
                let selectIndex = 0;
                selects.forEach(select => {
                    if (select.offsetParent !== null) {
                        const options = Array.from(select.options).map(o => o.text);
                        result.selects.push({
                            index: selectIndex++,
                            name: select.name || '',
                            id: select.id || '',
                            options: options,
                            selected: select.value,
                        });
                    }
                });

                // Links
                const links = document.querySelectorAll('a[href]');
                let linkIndex = 0;
                links.forEach(link => {
                    if (link.offsetParent === null) return;
                    const text = (link.innerText || link.getAttribute('aria-label') || '').trim();
                    if (!text || text.length < 2) return;
                    let href = link.getAttribute('href') || '';
                    if (href.startsWith('/')) href = window.location.origin + href;
                    if (!href.startsWith('http')) return;
                    result.links.push({
                        index: linkIndex++,
                        text: text,
                        href: href,
                    });
                });

                // Key text (prices, titles, headings, paragraphs, reviews)
                const textSelectors = [
                    'h1', 'h2', 'h3',
                    '.a-price', '[data-testid*="price"]', '.price', '[class*="price"]',
                    '[class*="error"]', '[class*="alert"]',
                    '#feature-bullets li', '#productDescription p',
                    '[data-hook="review-body"] span',
                    '[data-hook="review-title"] span',
                    '.a-profile-name',
                    '#availability span',
                    '.a-section p',
                ].join(', ');
                const textElements = document.querySelectorAll(textSelectors);
                const seenTexts = new Set();
                textElements.forEach(el => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length >= 3 && !seenTexts.has(text)) {
                        seenTexts.add(text);
                        result.text_content.push(text);
                    }
                });

                return result;
            }
        ''')

        elements['html'] = page_html
        return elements

    async def click(self, page: Page, selector: str) -> bool:
        """Click an element with human-like behavior."""
        try:
            await asyncio.sleep(random.uniform(0.5, 1.2))

            if ':has-text(' in selector or ':has(' in selector:
                locator = page.locator(selector)
                if await locator.count() == 0:
                    logger.warning("No element found for locator: %s", selector)
                    return False
                element = await locator.first.element_handle()
            else:
                element = await page.query_selector(selector)

            if not element:
                logger.warning("No element found: %s", selector)
                return False

            if not await element.is_visible():
                logger.warning("Element not visible: %s", selector)
                return False

            await element.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)

            try:
                await element.click(timeout=3000)
            except Exception:
                # Fallback to JS click
                await element.evaluate('el => el.click()')

            await asyncio.sleep(1)
            return True

        except Exception as e:
            logger.error("Click failed for %s: %s", selector, e)
            return False

    async def fill(self, page: Page, selector: str, value: str) -> bool:
        """Fill an input field with human-like typing."""
        try:
            await asyncio.sleep(random.uniform(0.5, 1.2))

            element = await page.query_selector(selector)
            if not element:
                logger.warning("No element found: %s", selector)
                return False

            if not await element.is_visible():
                logger.warning("Element not visible: %s", selector)
                return False

            # JS scroll + click to focus (avoids viewport check issues)
            await element.evaluate('el => { el.scrollIntoView({block: "center", behavior: "instant"}); }')
            await asyncio.sleep(0.2)
            await element.evaluate('el => el.click()')
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # Clear and type
            await element.evaluate('el => el.value = ""')
            await element.type(value, delay=random.randint(80, 160))

            # Dismiss autocomplete
            await element.press("Escape")
            await asyncio.sleep(0.3)

            return True

        except Exception as e:
            logger.error("Fill failed for %s: %s", selector, e)
            return False

    async def scroll(self, page: Page, direction: str = "down") -> None:
        """Scroll the page up or down."""
        pixels = 800 if direction == "down" else -800
        await page.evaluate(f'window.scrollBy(0, {pixels})')
        await asyncio.sleep(0.5)
        logger.info("Scrolled %s on %s", direction, page.url)

    async def go_back(self, page: Page) -> str:
        """Navigate back and return the new URL."""
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        await self._random_delay(500, 1000)
        new_url = page.url
        logger.info("Navigated back to: %s", new_url)
        return new_url

    async def select_option(self, page: Page, selector: str, value: str) -> bool:
        """Select a dropdown option by label."""
        try:
            element = await page.query_selector(selector)
            if not element:
                logger.warning("No select found: %s", selector)
                return False
            await element.select_option(label=value)
            return True
        except Exception as e:
            logger.error("Select failed for %s: %s", selector, e)
            return False

    async def close(self) -> None:
        """Shut down browser and Playwright."""
        for page in self._tabs:
            try:
                await page.close()
            except Exception:
                pass
        self._tabs.clear()
        self._active_tab_index = -1

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("Browser closed")

    @staticmethod
    async def _random_delay(min_ms: int = 500, max_ms: int = 2000):
        """Human-like delay."""
        await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)
