# TODO

## Goal
Add `fetch_url` tool + headless browser support to the pi-ddgs extension so agents can fetch and extract clean text from any page (static or JS-rendered), replacing SearXNG.

## Completed Tasks

### 1. Python backend — add `/fetch` endpoint (Done)
- [x] Add `requests` and `beautifulsoup4` dependencies to Dockerfile (`pip install`)
- [x] Add `GET /fetch?url=...` endpoint in `app/main.py` that:
  - Accepts a `url` query parameter
  - Sets a timeout of ~15 seconds (agents shouldn't wait on slow sites)
  - Strips the page title and extracts the main body text using BeautifulSoup (stripping scripts, styles, nav, etc.)
  - Returns JSON with `{ title, url, text }` — clean, LLM-friendly output

### 2. TypeScript extension — add `fetch_url` tool (Done)
- [x] Add `FetchResponse` interface and `fetchPage()` function in `pi-ddgs/src/ddgs.ts`
- [x] Add `fetchTimeoutMs` to config with default of 20s
- [x] Add new `fetch_url` tool registration in `pi-ddgs/index.ts` that:
  - Accepts a `url` string parameter (required)
  - Calls the new `/fetch` endpoint on the local API
  - Formats the response into readable text for the agent
- [x] Docker container built and running on port 8091

### 3. Headless browser backend (Done)
- [x] Added Playwright + Chromium to the existing Dockerfile via `playwright install --with-deps chromium`
- [x] Single browser launched once at app startup (FastAPI lifespan), fresh context per request
- [x] Folded rendering into the existing `/fetch` endpoint as a `?render=true` query param (one container, one endpoint)
- [x] Realistic Chrome user-agent + viewport on the rendered context
- [x] `playwright-stealth` applied to each context — patches `navigator.webdriver`, `window.chrome`, `navigator.plugins`, WebGL vendor/renderer, etc. Verified against bot.sannysoft.com (all stealth checks pass)
- [x] Response now includes `rendered: bool` so the client/agent can tell which path was used

### 4. Extension — render fallback (Done)
- [x] `fetchPage(url, render?)` in `ddgs.ts` now passes `render=true` and uses a longer timeout (3x) when rendering
- [x] `fetch_url` tool exposes an optional `render` boolean for the agent to force headless mode
- [x] Auto-fallback: if static fetch returns <200 chars of text and no error, the tool silently retries with `render=true` and uses whichever returns more text
- [x] Tool result and `renderCall`/`renderResult` indicate when a render path was used

### Bonus fix
- [x] `searchNews()` in `ddgs.ts` was returning the bare results array instead of `{ results }`, so `web_search_news` was silently always returning "No results found." Fixed.

### Anti-bot upgrades
- [x] Static path now uses `curl_cffi` with `impersonate="chrome"` for Chrome-grade TLS+HTTP2 fingerprint (defeats JA3/JA4 blocking)
- [x] Render path now uses real Google Chrome (`channel="chrome"`) instead of bundled Chromium, plus `--disable-blink-features=AutomationControlled`
- [x] **Camoufox** added as a second render engine. C++-patched Firefox fork with anti-fingerprint baked in. Slower (~2-3s extra), launched once per app lifespan. Pass `engine=camoufox` to use it directly.
- [x] **Three-tier fallback** in `fetch_url` tool:
  1. static (curl_cffi) → if empty/short, try
  2. render with chrome → if blocked-looking (len < 200 or title matches /robot challenge|forbidden|just a moment|.../i), try
  3. render with camoufox → final answer
- [x] Host rewrite map (`HOST_REWRITES` in `main.py`) — applied before fetch on both static and render paths. Easy to add more (e.g. `twitter.com` → `nitter.net`, `medium.com` → `scribe.rip`).
- ✅ **Cloudflare standard managed challenge defeated by Camoufox** (franksworld now returns 5.5KB of real article text). The auto-fallback chain handles it transparently.
- ❌ **nowsecure.nl** still wins — but that's `nodriver`'s purpose-built test page tuned to detect every popular evasion lib, not a real-world site. Acceptable.
- ✅ **Reddit also works** via the combination of `HOST_REWRITES` (reddit.com → old.reddit.com) and `engine=camoufox`. Static path alone is still blocked, but the chrome→camoufox auto-fallback handles it transparently. ~7-8KB of real subreddit content returned.

## Notes
- Static HTML extraction via BeautifulSoup works great for most sites (Hacker News, Wikipedia, blogs, docs, modern SSR'd sites like react.dev)
- True client-rendered SPAs are now handled via the headless path (verified on react.dev with `render=true` returning ~14KB clean text)
- **Most Cloudflare-protected pages now work via the Camoufox fallback** — the tool transparently retries chrome→camoufox when Chrome hits a challenge. Latency cost: +5-10s on Cloudflare-protected URLs (Camoufox is slower than Chrome).
- **Hardest tier (Turnstile interactive challenge, behavioral-signal sites like Reddit, IP-rep sites)** still wins. No free, no-proxy way around those in 2026.
- Render adds ~1–3s per call vs ~100–500ms for the static path — that's why static is the default and render is opt-in (or auto-fallback when static returns nothing).
