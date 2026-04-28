# ddgs-api

Local web search and page fetch for [Pi](https://www.npmjs.com/package/@mariozechner/pi-coding-agent). Runs in Docker, no API keys, no rate limits.

The fetch path has three layers: a fast static HTTP client (`curl_cffi`), real headless Chrome, and [Camoufox](https://github.com/daijro/camoufox) (a Firefox fork that's painful for anti-bot stacks to detect). The extension layers them automatically so the agent gets useful text out of most pages without thinking about it.

## Setup

Clone the repo and start the backend:

```bash
docker compose up -d --build
```

First build takes 5–10 minutes and the image is around 3GB. It downloads Chrome, Camoufox, and a GeoIP database, so be patient. Once it's up:

```bash
curl http://localhost:8091/health
# {"status":"ok"}
```

Then install the extension into Pi:

```bash
pi install npm:@arcadia64/pi-ddgs
```

Reload Pi. You'll have four tools available: `web_search`, `web_search_news`, `get_search_results`, and `fetch_url`.

## Config

Drop a JSON file at `~/.pi/ddgs.json` to override defaults. Every field is optional.

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
| `ddgsApiUrl` | `http://localhost:8091` | Backend URL. Point this at a remote box if you split machines. |
| `timeoutMs` | 30000 | Search request timeout. |
| `fetchTimeoutMs` | 20000 | Static fetch timeout. Render paths multiply this by 3 (Chrome) or 5 (Camoufox). |
| `maxResults` | 10 | Default result count. |
| `safesearch` | `"off"` | `"off"`, `"moderate"`, `"on"`. |
| `region` | `"us-en"` | DDG region code. |
| `defaultEngine` | `"chrome"` | `"chrome"` is fast, `"camoufox"` is slower but beats more anti-bot. |
| `searchCacheSize` | 50 | LRU bound on cached search results. |

## What it can and can't fetch

Static HTML, server-rendered SPAs, and most blogs/docs work fine through the fast static path. Pure client-rendered SPAs fall back to Chrome. Cloudflare's standard managed challenge falls through to Camoufox and usually gets the page. Reddit works because the backend rewrites `reddit.com` to `old.reddit.com` before fetching.

Things it doesn't do: Cloudflare Turnstile, interactive challenges, and sites that block on IP reputation or behavioral signals. Those need residential proxies or real auth, which is out of scope.

---

## Beyond the basics

### Container hygiene

`restart: unless-stopped` and `mem_limit: 2g` are set in `docker-compose.yml`. If a browser leak grows past 2GB the kernel kills the container and Docker brings it back. Each fetch creates a fresh browser context and destroys it before returning, so no cookies, history, or session state persists between requests.

### Backend endpoints

| Path | Purpose |
|---|---|
| `/search?q=&max_results=&safesearch=&region=` | DDG web search |
| `/search/news?q=&max_results=&safesearch=&region=` | DDG news search |
| `/fetch?url=&render=&engine=` | Fetch + clean text. `render=true` uses a headless browser. `engine` is `chrome` (default) or `camoufox`. |
| `/health` | Liveness |

### Host rewrites

`app/main.py` has a small map that rewrites hosts before fetching:

```python
HOST_REWRITES = {
    "reddit.com":      "old.reddit.com",
    "www.reddit.com":  "old.reddit.com",
}
```

Add others if useful — `medium.com` → `scribe.rip`, `twitter.com` → `nitter.net`, etc.

### Installing the extension from a local path

If you're hacking on the extension and don't want to bump npm versions every time, point Pi at the cloned directory instead:

```json
{
  "packages": ["C:/path/to/ddgs-api/pi-ddgs"]
}
```

Reload Pi. Edit `pi-ddgs/index.ts` freely.

### Split setup (extension on machine A, backend on machine B)

Run `docker compose up -d --build` on machine B and make sure port 8091 is reachable from machine A. On machine A, set `"ddgsApiUrl": "http://<machine-B-ip>:8091"` in `~/.pi/ddgs.json`, install the extension, reload Pi.

### Layout

```
ddgs-api/
├── docker-compose.yml
├── Dockerfile
├── app/
│   └── main.py             # FastAPI backend
└── pi-ddgs/                # Pi extension
    ├── package.json
    ├── index.ts
    └── src/
        ├── ddgs.ts
        └── config.ts
```
