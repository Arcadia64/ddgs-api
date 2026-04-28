import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
import { search, searchNews, fetchPage, type FetchResponse } from "./src/ddgs.js";
import { loadConfig } from "./src/config.js";

const searchCache = new Map<string, { query: string; results: any[] }>();

function cacheSearch(id: string, entry: { query: string; results: any[] }): void {
  const { searchCacheSize } = loadConfig();
  // Re-insert to mark as most recent (Map preserves insertion order).
  if (searchCache.has(id)) searchCache.delete(id);
  searchCache.set(id, entry);
  while (searchCache.size > searchCacheSize) {
    const oldest = searchCache.keys().next().value;
    if (oldest === undefined) break;
    searchCache.delete(oldest);
  }
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function formatSearchResults(results: any[]): string {
  if (results.length === 0) return "No results found.";
  return results.map((r, i) => {
    const snippet = r.snippet || "";
    const truncated = snippet.length > 200 ? snippet.slice(0, 200) + "..." : snippet;
    return `${i + 1}. **${r.title}**\n   ${r.link}\n   ${truncated}`;
  }).join("\n\n");
}

const BLOCKED_TITLE_RE = /robot challenge|just a moment|attention required|forbidden|access denied|verifying you are human|are you a robot|cloudflare/i;
const BLOCKED_TEXT_RE = /you'?ve been blocked|access to this page is forbidden|enable javascript and cookies/i;

function looksBlocked(r: { title?: string; text?: string }, minLen: number): boolean {
  const text = (r.text || "").trim();
  if (text.length < minLen) return true;
  if (BLOCKED_TITLE_RE.test(r.title || "")) return true;
  if (BLOCKED_TEXT_RE.test(text.slice(0, 600))) return true;
  return false;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "web_search",
    label: "Web Search",
    description: "Search the web using local DuckDuckGo API (no rate limits, no captcha)",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      limit: Type.Optional(Type.Number({ description: "Max results", default: 10 })),
    }),

    async execute(_id, params, signal) {
      if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };

      try {
        const { results } = await search(params.query, params.limit, signal);
        const searchId = generateId();
        cacheSearch(searchId, { query: params.query, results });

        return {
          content: [{ type: "text", text: formatSearchResults(results) }],
          details: { searchId, resultCount: results.length, query: params.query },
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }],
          details: { error: String(err) },
        };
      }
    },

    renderCall(args, theme) {
      const q = (args as any).query || "";
      const display = q.length > 50 ? q.slice(0, 47) + "..." : q;
      return new Text(theme.fg("toolTitle", "search ") + theme.fg("accent", `"${display}"`), 0, 0);
    },

    renderResult(result, _opts, theme) {
      const count = (result.details as any)?.resultCount || 0;
      return new Text(theme.fg("success", `${count} results`), 0, 0);
    },
  });

  pi.registerTool({
    name: "web_search_news",
    label: "Search News",
    description: "Search news using local DuckDuckGo News API (no rate limits)",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      limit: Type.Optional(Type.Number({ description: "Max results", default: 10 })),
    }),

    async execute(_id, params, signal) {
      if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };

      try {
        const { results } = await searchNews(params.query, params.limit, signal);
        const searchId = generateId();
        cacheSearch(searchId, { query: params.query, results });

        return {
          content: [{ type: "text", text: formatSearchResults(results) }],
          details: { searchId, resultCount: results.length, query: params.query },
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }],
          details: { error: String(err) },
        };
      }
    },

    renderCall(args, theme) {
      const q = (args as any).query || "";
      const display = q.length > 50 ? q.slice(0, 47) + "..." : q;
      return new Text(theme.fg("toolTitle", "search-news ") + theme.fg("accent", `"${display}"`), 0, 0);
    },

    renderResult(result, _opts, theme) {
      const count = (result.details as any)?.resultCount || 0;
      return new Text(theme.fg("success", `${count} results`), 0, 0);
    },
  });

  pi.registerTool({
    name: "get_search_results",
    label: "Get Search Results",
    description: "Retrieve previous search results by ID",
    parameters: Type.Object({
      searchId: Type.String(),
    }),

    async execute(_id, params, signal) {
      if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };
      const cached = searchCache.get(params.searchId);
      if (!cached) return { content: [{ type: "text", text: "Search not found" }] };
      // Refresh recency on access.
      cacheSearch(params.searchId, cached);
      return {
        content: [{ type: "text", text: `Query: "${cached.query}"\n\n${formatSearchResults(cached.results)}` }],
      };
    },
  });

  pi.registerTool({
    name: "fetch_url",
    label: "Fetch URL",
    description: "Fetch a web page and extract clean text for LLM consumption. Tries static HTML first; falls back to headless Chrome if static is empty or looks like a challenge page; falls back further to Camoufox (anti-bot Firefox) if Chrome hits a challenge. Pass render=true to skip static. Pass engine='camoufox' to skip Chrome.",
    parameters: Type.Object({
      url: Type.String({ description: "URL to fetch" }),
      render: Type.Optional(Type.Boolean({ description: "Force headless browser rendering (slower; needed for JS-heavy pages)" })),
      engine: Type.Optional(Type.Union([Type.Literal("chrome"), Type.Literal("camoufox")], { description: "Render engine: 'chrome' (fast) or 'camoufox' (slower, beats more anti-bot). Default from config." })),
    }),

    async execute(_id, params, signal) {
      if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };
      const MIN_USEFUL_LEN = 200;

      // A result is "no good" if it errored, came back blocked-looking, or is too short.
      const noGood = (r: FetchResponse): boolean => !!r.error || looksBlocked(r, MIN_USEFUL_LEN);
      // Pick the better of two attempts: prefer no-error, then prefer longer text.
      const pickBetter = (a: FetchResponse, b: FetchResponse): FetchResponse => {
        const aOk = !a.error;
        const bOk = !b.error;
        if (aOk && !bOk) return a;
        if (!aOk && bOk) return b;
        return b.text.trim().length >= a.text.trim().length ? b : a;
      };

      try {
        const config = loadConfig();
        const requestedEngine = params.engine || config.defaultEngine;
        let result = await fetchPage(params.url, params.render === true, requestedEngine, signal);

        // Stage 1: static was no good → render with chosen engine.
        if (!params.render && noGood(result)) {
          if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };
          const rendered = await fetchPage(params.url, true, requestedEngine, signal);
          result = pickBetter(result, rendered);
        }

        // Stage 2: chrome render still no good → retry with camoufox.
        // Only fires when the agent didn't pin an engine explicitly.
        if (!params.engine && (result.engine === "chrome" || result.engine === undefined) && noGood(result)) {
          if (signal?.aborted) return { content: [{ type: "text", text: "Aborted" }] };
          const camo = await fetchPage(params.url, true, "camoufox", signal);
          result = pickBetter(result, camo);
        }

        if (result.error) return { content: [{ type: "text", text: `Error fetching ${result.url}: ${result.error}` }] };

        const tag = result.rendered ? ` (rendered:${result.engine || "chrome"})` : "";
        return {
          content: [{
            type: "text",
            text: `# ${result.title}${tag}\n\nURL: ${result.url}\n\n${result.text}`,
          }],
          details: { url: result.url, title: result.title, rendered: result.rendered === true, engine: result.engine },
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }],
          details: { error: String(err) },
        };
      }
    },

    renderCall(args, theme) {
      const u = (args as any).url || "";
      const display = u.length > 60 ? u.slice(0, 57) + "..." : u;
      const a = args as any;
      let tag = "fetch_url ";
      if (a.render) tag = `fetch_url[${a.engine || "chrome"}] `;
      else if (a.engine) tag = `fetch_url[${a.engine}] `;
      return new Text(theme.fg("toolTitle", tag) + theme.fg("accent", `"${display}"`), 0, 0);
    },

    renderResult(result, _opts, theme) {
      const d = result.details as any;
      const title = d?.title || "Unknown";
      const tag = d?.rendered ? ` (${d.engine || "chrome"})` : "";
      return new Text(theme.fg("success", title + tag), 0, 0);
    },
  });
}
