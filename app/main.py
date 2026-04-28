from contextlib import asynccontextmanager
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

playwright_instance = None
browser = None
stealth = Stealth()

camoufox_manager = None
camoufox_browser = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser, camoufox_manager, camoufox_browser

    playwright_instance = await async_playwright().start()
    # channel="chrome" launches real Google Chrome (installed via `playwright install chrome`)
    # rather than the bundled Chromium. Real Chrome has more realistic fingerprint surface
    # area (Widevine, fonts, codecs) which helps with anti-bot detection.
    browser = await playwright_instance.chromium.launch(
        channel="chrome",
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )

    # Camoufox = Firefox fork patched at C++ level against fingerprinting. Slower to launch
    # but far more resistant to managed-challenge anti-bot than Playwright Chrome.
    # Manual __aenter__/__aexit__ keeps it alive across the app lifespan.
    camoufox_manager = AsyncCamoufox(headless=True, geoip=True)
    try:
        camoufox_browser = await camoufox_manager.__aenter__()
    except Exception as e:
        print(f"Camoufox launch failed: {e}")
        camoufox_manager = None
        camoufox_browser = None

    try:
        yield
    finally:
        if camoufox_manager is not None:
            try:
                await camoufox_manager.__aexit__(None, None, None)
            except Exception:
                pass
        if browser is not None:
            await browser.close()
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
    if camoufox_browser is None:
        raise RuntimeError("Camoufox not available")
    page = await camoufox_browser.new_page()
    try:
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        html = await page.content()
        return extract_clean_text(html)
    finally:
        await page.close()


async def fetch_rendered(url: str, timeout_ms: int = 30000):
    """Fetch via headless Chromium, returning (title, clean_text)."""
    if browser is None:
        raise RuntimeError("Browser not initialized")

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
