# ddgs-api

A local, free, no-rate-limit web search + page-fetch service for agentic LLM tools, plus a Pi (`pi-coding-agent`) extension that wraps it. Runs in Docker, no external API keys.

## What it does

- **Web search** via DuckDuckGo (no captcha, no rate limits, no API key)
- **News search** via DuckDuckGo News
- **Page fetch with clean text extraction** — three-tier strategy:
  1. Static HTTP via `curl_cffi` (Chrome TLS fingerprint impersonation)
  2. Headless Chrome render (real Chrome, not bundled Chromium) + `playwright-stealth`
  3. Camoufox (Firefox fork patched against fingerprinting) — beats most Cloudflare managed challenges

The extension exposes `web_search`, `web_search_news`, `get_search_results`, and `fetch_url` tools to the agent. `fetch_url` auto-falls-back through the three tiers transparently.

## Architecture

```
┌─────────────────────────┐     HTTP      ┌──────────────────────┐
│ Pi extension (pi-ddgs/) │  ─────────▶   │ Docker container     │
│ - web_search            │   :8091       │ - FastAPI            │
│ - web_search_news       │               │ - DDGS               │
│ - fetch_url             │               │ - curl_cffi          │
│ - get_search_results    │               │ - Playwright (Chrome)│
└─────────────────────────┘               │ - Camoufox           │
                                          └──────────────────────┘
```

## Quickstart

### 1. Start the backend

```bash
docker compose up -d --build
curl http://localhost:8091/health   # {"status":"ok"}
```

First build takes 5-10 min (downloads Chromium, Chrome, Camoufox + GeoIP). Image is ~3GB.

### 2. Register the extension with Pi

**Option A — npm (cleanest):**

```bash
pi install npm:@arcadia64/pi-ddgs
```

Or edit `~/.pi/agent/settings.json` directly:

```json
{
  "packages": ["npm:@arcadia64/pi-ddgs"]
}
```

Pi auto-installs missing packages on startup.

**Option B — local path (for development):**

Clone the repo and add the path to `pi-ddgs/` to `packages`:

```json
{
  "packages": ["C:/path/to/ddgs-api/pi-ddgs"]
}
```

Reload Pi. The four tools will be available.

### 3. (Optional) Drop a config at `~/.pi/ddgs.json`

All fields are optional — defaults work without a config file.

```json
{
  "ddgsApiUrl": "http://localhost:8091",
  "timeoutMs": 30000,
  "fetchTimeoutMs": 20000,
  "maxResults": 10,
  "safesearch": "off",
  "region": "us-en",
  "defaultEngine": "chrome",
  "searchCacheSize": 50
}
```

| Field | Default | Notes |
|---|---|---|
| `ddgsApiUrl` | `http://localhost:8091` | Backend URL. Override to point at a remote instance. |
| `timeoutMs` | 30000 | Search request timeout |
| `fetchTimeoutMs` | 20000 | Static fetch timeout. Render path uses 3× this for Chrome and 5× for Camoufox. |
| `maxResults` | 10 | Default result count |
| `safesearch` | `"off"` | DDG safesearch: `"off"`, `"moderate"`, `"on"` |
| `region` | `"us-en"` | DDG region code |
| `defaultEngine` | `"chrome"` | Initial render engine: `"chrome"` (fast) or `"camoufox"` (slower, beats more anti-bot) |
| `searchCacheSize` | 50 | Max entries in the in-memory `searchCache` (LRU eviction) |

## Installing on another PC

The extension and the backend can be on the same machine or split.

**Same-machine setup (simplest):**

1. Clone the repo and `docker compose up -d --build`.
2. Add `"npm:@arcadia64/pi-ddgs"` to `packages` in `~/.pi/agent/settings.json` (or use a local path if you prefer dev mode).
3. Reload Pi.

**Split setup (extension on machine A, backend on machine B):**

1. Run `docker compose up -d --build` on machine B. Make sure the firewall allows inbound on port 8091.
2. On machine A, add `"npm:@arcadia64/pi-ddgs"` to `~/.pi/agent/settings.json` `packages`.
3. Create `~/.pi/ddgs.json` on machine A with `"ddgsApiUrl": "http://<machine-B-ip>:8091"`.
4. Reload Pi.

## Backend endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/search?q=&max_results=&safesearch=&region=` | DDG web search |
| GET | `/search/news?q=&max_results=&safesearch=&region=` | DDG news search |
| GET | `/fetch?url=&render=&engine=` | Fetch + extract clean text. `render=true` uses headless browser. `engine=chrome` (default) or `engine=camoufox`. |

## Host rewrites

The backend transparently rewrites certain hosts before fetching, defined in `app/main.py`:

```python
HOST_REWRITES = {
    "reddit.com":      "old.reddit.com",
    "www.reddit.com":  "old.reddit.com",
}
```

Add more if useful (e.g. `medium.com` → `scribe.rip`, `twitter.com` → `nitter.net`).

## What works / what doesn't

| Site type | Result |
|---|---|
| Plain HTML (HN, Wikipedia, blogs) | Static path |
| SSR'd SPAs (react.dev, Next.js sites) | Static path |
| Pure CSR SPAs | Auto-fallback to Chrome render |
| Cloudflare standard managed challenge (e.g., franksworld) | Auto-fallback to Camoufox ✅ |
| Reddit (via `old.reddit.com` rewrite) | Auto-fallback to Camoufox ✅ |
| Cloudflare Turnstile / interactive challenge | ❌ — no free tool reliably beats this |
| Sites with IP-rep / behavioral defense beyond fingerprinting | ❌ — needs proxies or auth |

## Container hygiene

- `restart: unless-stopped` — auto-recovers from crashes
- `mem_limit: 2g` — kernel kills the container if a browser leak runs away; Docker brings it back
- Each `/fetch?render=true` uses a fresh browser context that is destroyed before the response returns. **No cookies, sessions, or history persist between fetches.** The browser process itself stays loaded for speed.
- Hit `http://localhost:8091/health` to verify liveness anytime.

## Layout

```
ddgs-api/
├── docker-compose.yml
├── Dockerfile
├── app/
│   └── main.py             # FastAPI backend
└── pi-ddgs/                # Pi extension
    ├── package.json
    ├── index.ts            # Tool registrations
    └── src/
        ├── ddgs.ts         # HTTP client
        └── config.ts       # Loads ~/.pi/ddgs.json
```
