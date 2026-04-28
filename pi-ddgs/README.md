# pi-ddgs

Pi ([`pi-coding-agent`](https://www.npmjs.com/package/@mariozechner/pi-coding-agent)) extension that gives the agent web search and page fetch via a local Docker backend with a three-tier anti-bot fallback (curl_cffi → real Chrome → Camoufox).

**Source / backend / docs:** [github.com/Arcadia64/ddgs-api](https://github.com/Arcadia64/ddgs-api) — the Docker backend lives there too. This package is the Pi extension half; you'll want to clone the repo and run the backend container alongside it.

## Tools

| Name | Purpose |
|---|---|
| `web_search` | DuckDuckGo web search |
| `web_search_news` | DuckDuckGo news search |
| `get_search_results` | Retrieve a previous search by ID (cached in memory, LRU-bounded) |
| `fetch_url` | Fetch a URL and extract clean text. Auto-falls-back through three tiers: static (curl_cffi) → Chrome render → Camoufox render. Honors abort signal. |

## Install

You need the backend running first. Clone [the repo](https://github.com/Arcadia64/ddgs-api) and run:

```bash
docker compose up -d --build
```

Then install the Pi extension.

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

Add the absolute path to the cloned `pi-ddgs/` directory to `packages`:

```json
{
  "packages": ["C:/absolute/path/to/ddgs-api/pi-ddgs"]
}
```

Reload Pi.

## Config

Optional. Defaults work without a file. Drop a JSON file at `~/.pi/ddgs.json` to override any field — see the [full config table in the project README](https://github.com/Arcadia64/ddgs-api#3-optional-drop-a-config-at-pidgsjson).

Common overrides:

```json
{
  "ddgsApiUrl": "http://my-other-pc:8091",
  "defaultEngine": "camoufox",
  "safesearch": "off"
}
```

## License

MIT
