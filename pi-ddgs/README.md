# pi-ddgs

Pi (`pi-coding-agent`) extension that gives the agent web search and page fetch via the local `ddgs-api` Docker backend.

See the [project README](../README.md) for the full picture (backend, architecture, anti-bot strategy).

## Tools

| Name | Purpose |
|---|---|
| `web_search` | DuckDuckGo web search |
| `web_search_news` | DuckDuckGo news search |
| `get_search_results` | Retrieve a previous search by ID (cached in memory, LRU-bounded) |
| `fetch_url` | Fetch a URL and extract clean text. Auto-falls-back through three tiers: static (curl_cffi) → Chrome render → Camoufox render. Honors abort signal. |

## Install

You need the backend running first (`docker compose up -d --build` in the [repo root](../README.md)).

### Option 1 — npm (cleanest)

```bash
pi install npm:@arcadia64/pi-ddgs
```

Or add it directly to `~/.pi/agent/settings.json`:

```json
{
  "packages": ["npm:@arcadia64/pi-ddgs"]
}
```

Pi auto-installs missing packages on startup.

### Option 2 — local path (development)

Clone the repo and add the absolute path to `pi-ddgs/` to `packages`:

```json
{
  "packages": ["C:/absolute/path/to/ddgs-api/pi-ddgs"]
}
```

Reload Pi.

## Config

Optional. Defaults work without a file. Drop a JSON file at `~/.pi/ddgs.json` to override any field — see the [project README's config table](../README.md#3-optional-drop-a-config-at-pidgsjson) for the full list.

Common overrides:

```json
{
  "ddgsApiUrl": "http://my-other-pc:8091",
  "defaultEngine": "camoufox",
  "safesearch": "off"
}
```
