import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from ddgs import DDGS
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from camoufox.async_api import AsyncCamoufox

# Host rewrites: swap to less-protected / cleaner mirrors before fetching.
# Rewrite is applied to both static and rendered paths.
HOST_REWRITES = {
    "reddit.com": "old.reddit.com",
    "www.reddit.com": "old.reddit.com",
}


def rewrite_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        new_host = HOST_REWRITES.get(parsed.hostname or "")
        if new_host:
            netloc = new_host
            if parsed.port:
                netloc = f"{new_host}:{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


# Long-lived browser processes leak memory regardless of activity (renderer caches,
# zombie children, fragmentation). The pool rotates browsers proactively but never
# closes one that's still serving a request — old browsers stay alive until their
# last in-flight request finishes. A failed relaunch keeps the current browser.
class BrowserPool:
    def __init__(
        self,
        launch: Callable[[], Awaitable[tuple[Any, Callable[[], Awaitable[None]]]]],
        max_requests: int,
        max_age_seconds: float,
        name: str,
    ):
        self._launch = launch
        self._max_requests = max_requests
        self._max_age = max_age_seconds
        self._name = name
        self._current: Any = None
        # id(browser) -> (browser, close_fn, in_flight_count)
        self._tracked: dict[int, tuple[Any, Callable[[], Awaitable[None]], int]] = {}
        self._current_count = 0
        self._current_started_at = 0.0
        self._rotating = False

    async def start(self):
        browser, close = await self._launch()
        self._current = browser
        self._tracked[id(browser)] = (browser, close, 0)
        self._current_started_at = time.monotonic()

    async def stop(self):
        for _, (_, close, _) in list(self._tracked.items()):
            try:
                await close()
            except Exception as e:
                print(f"{self._name} close failed during shutdown: {e}")
        self._tracked.clear()
        self._current = None

    @asynccontextmanager
    async def acquire(self):
        if self._current is None:
            raise RuntimeError(f"{self._name} pool not started")

        if self._should_rotate():
            self._rotating = True
            asyncio.create_task(self._rotate())

        # Snapshot + bump must be atomic; safe here because there are no awaits
        # between reading self._current and writing the in-flight count.
        browser = self._current
        bid = id(browser)
        b, close, count = self._tracked[bid]
        self._tracked[bid] = (b, close, count + 1)
        self._current_count += 1

        try:
            yield browser
        finally:
            b, close, count = self._tracked[bid]
            count -= 1
            if browser is not self._current and count == 0:
                del self._tracked[bid]
                asyncio.create_task(self._close_quiet(close))
            else:
                self._tracked[bid] = (b, close, count)

    def _should_rotate(self) -> bool:
        if self._current is None or self._rotating:
            return False
        age = time.monotonic() - self._current_started_at
        return self._current_count >= self._max_requests or age >= self._max_age

    async def _rotate(self):
        try:
            try:
                new_browser, new_close = await self._launch()
            except Exception as e:
                # Reset counters so we don't retry on every subsequent request.
                print(f"{self._name} rotation launch failed, keeping current: {e}")
                self._current_started_at = time.monotonic()
                self._current_count = 0
                return

            old_browser = self._current
            old_id = id(old_browser)
            self._current = new_browser
            self._tracked[id(new_browser)] = (new_browser, new_close, 0)
            self._current_count = 0
            self._current_started_at = time.monotonic()

            _, old_close, old_count = self._tracked[old_id]
            if old_count == 0:
                del self._tracked[old_id]
                asyncio.create_task(self._close_quiet(old_close))
            # else: last-out request closes it on release
        finally:
            self._rotating = False

    async def _close_quiet(self, close):
        try:
            await close()
        except Exception as e:
            print(f"{self._name} close failed: {e}")


playwright_instance = None
chrome_pool: BrowserPool | None = None
camoufox_pool: BrowserPool | None = None
stealth = Stealth()
# Camoufox is heavier and flakier under parallel page load than Chrome.
# Bound concurrent renders so bursts queue instead of thrashing the browser.
camoufox_semaphore = asyncio.Semaphore(2)


async def _launch_chromium():
    assert playwright_instance is not None
    # channel="chrome" launches real Google Chrome (installed via `playwright install chrome`)
    # rather than the bundled Chromium. Real Chrome has more realistic fingerprint surface
    # area (Widevine, fonts, codecs) which helps with anti-bot detection.
    browser = await playwright_instance.chromium.launch(
        channel="chrome",
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    return browser, browser.close


async def _launch_camoufox():
    # Camoufox = Firefox fork patched at C++ level against fingerprinting. Slower to launch
    # but far more resistant to managed-challenge anti-bot than Playwright Chrome.
    manager = AsyncCamoufox(headless=True, geoip=True)
    browser = await manager.__aenter__()

    async def close():
        await manager.__aexit__(None, None, None)

    return browser, close


@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, chrome_pool, camoufox_pool

    playwright_instance = await async_playwright().start()

    chrome_pool = BrowserPool(
        launch=_launch_chromium,
        max_requests=200,
        max_age_seconds=30 * 60,
        name="chrome",
    )
    await chrome_pool.start()

    camoufox_pool = BrowserPool(
        launch=_launch_camoufox,
        max_requests=50,
        max_age_seconds=60 * 60,
        name="camoufox",
    )
    try:
        await camoufox_pool.start()
    except Exception as e:
        print(f"Camoufox launch failed, /fetch?engine=camoufox will be unavailable: {e}")
        camoufox_pool = None

    try:
        yield
    finally:
        if camoufox_pool is not None:
            await camoufox_pool.stop()
        if chrome_pool is not None:
            await chrome_pool.stop()
        if playwright_instance is not None:
            await playwright_instance.stop()


app = FastAPI(title="Local DDG Search API", lifespan=lifespan)


def do_search(query: str, max_results: int = 10, region: str = "us-en", safesearch: str = "moderate"):
    """Sync wrapper for the async ddgs package."""
    results = []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                max_results=max_results,
            ))
    except Exception as e:
        print(f"DDG search error: {e}")
    return results

@app.get("/search")
def search(
    q: str = Query(...),
    max_results: int = 10,
    region: str = "us-en",
    safesearch: str = Query("off", description="DDG safesearch: 'on', 'moderate', or 'off'"),
):
    try:
        results = do_search(q, max_results, region=region, safesearch=safesearch)
        formatted = [
            {
                "title": r.get("title", "Untitled"),
                "link": r.get("href", ""),
                "snippet": r.get("body", "")
            } for r in results
        ]
        return {"results": formatted, "total": len(formatted)}
    except Exception as e:
        return {"results": [], "error": str(e), "total": 0}

@app.get("/search/news")
def search_news(
    q: str = Query(...),
    max_results: int = 10,
    region: str = "us-en",
    safesearch: str = Query("off", description="DDG safesearch: 'on', 'moderate', or 'off'"),
):
    try:
        results = do_search(f"news {q}", max_results, region=region, safesearch=safesearch)
        formatted = [
            {
                "title": r.get("title", "Untitled"),
                "link": r.get("href", ""),
                "snippet": r.get("body", ""),
            } for r in results
        ]
        return {"results": formatted, "total": len(formatted)}
    except Exception as e:
        return {"results": [], "error": str(e), "total": 0}

def extract_clean_text(html: str):
    """Extract clean body text from HTML, stripping scripts, styles, nav, etc."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"

    content = soup.find("article") or soup.find("main") or soup.find("body")
    if content:
        text = content.get_text("\n", strip=True)
    else:
        text = soup.get_text("\n", strip=True)

    lines = [line for line in text.splitlines() if line.strip()]
    clean = "\n\n".join(lines)

    return title, clean


async def fetch_camoufox(url: str, timeout_ms: int = 30000):
    """Fetch via Camoufox (anti-fingerprint Firefox), returning (title, clean_text)."""
    if camoufox_pool is None:
        raise RuntimeError("Camoufox not available")
    async with camoufox_semaphore, camoufox_pool.acquire() as browser:
        context = await browser.new_context()
        try:
            page = await context.new_page()
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            html = await page.content()
            return extract_clean_text(html)
        finally:
            await context.close()


async def fetch_rendered(url: str, timeout_ms: int = 30000):
    """Fetch via headless Chromium, returning (title, clean_text)."""
    if chrome_pool is None:
        raise RuntimeError("Browser not initialized")
    async with chrome_pool.acquire() as browser:
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        await stealth.apply_stealth_async(context)
        try:
            page = await context.new_page()
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            # Best-effort wait for the SPA to settle. Many sites never go fully idle,
            # so we cap this and proceed regardless.
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            html = await page.content()
            return extract_clean_text(html)
        finally:
            await context.close()


@app.get("/fetch")
async def fetch_url(
    url: str = Query(...),
    render: bool = False,
    engine: str = Query("chrome", description="Render engine: 'chrome' (fast) or 'camoufox' (anti-bot Firefox fork)"),
):
    """Fetch a URL and extract clean, LLM-friendly text.

    Set render=true to use a headless browser for JS-rendered pages.
    Set engine=camoufox to use the more aggressive anti-bot Firefox fork.
    """
    fetched_url = rewrite_url(url)

    if render:
        try:
            if engine == "camoufox":
                title, text = await fetch_camoufox(fetched_url)
            else:
                title, text = await fetch_rendered(fetched_url)
            return {"title": title, "url": fetched_url, "text": text, "rendered": True, "engine": engine}
        except Exception as e:
            return {"error": f"render failed: {e}", "title": "", "url": fetched_url, "text": "", "rendered": True, "engine": engine}

    try:
        # impersonate="chrome" uses curl-impersonate's TLS+HTTP2 fingerprint, defeating
        # JA3/JA4 fingerprint blocking that plain `requests` always trips.
        resp = curl_requests.get(fetched_url, timeout=15, impersonate="chrome")
        resp.raise_for_status()
        title, text = extract_clean_text(resp.text)
        return {"title": title, "url": fetched_url, "text": text, "rendered": False}
    except Exception as e:
        return {"error": str(e), "title": "", "url": fetched_url, "text": "", "rendered": False}


@app.get("/health")
def health():
    return {"status": "ok"}
