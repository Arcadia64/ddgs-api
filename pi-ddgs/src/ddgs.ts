import { loadConfig, type RenderEngine } from "./config.js";

export type { RenderEngine } from "./config.js";

export interface SearchResult {
  title: string;
  link: string;
  snippet?: string;
}

export interface SearchResponse {
  results: SearchResult[];
}

// Combine an external AbortSignal (from the Pi tool's caller) with our own
// timeout-driven AbortController so either can cancel the request.
function makeSignal(externalSignal: AbortSignal | undefined, timeoutMs: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(new Error("Request timed out")), timeoutMs);
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort(externalSignal.reason);
    else externalSignal.addEventListener("abort", () => controller.abort(externalSignal.reason), { once: true });
  }
  return { signal: controller.signal, cancel: () => clearTimeout(timeout) };
}

export async function search(query: string, limit?: number, externalSignal?: AbortSignal): Promise<SearchResponse> {
  const config = loadConfig();
  const url = new URL(`${config.ddgsApiUrl}/search`);

  url.searchParams.set("q", query);
  url.searchParams.set("max_results", String(limit || config.maxResults));
  url.searchParams.set("safesearch", config.safesearch);
  url.searchParams.set("region", config.region);

  const { signal, cancel } = makeSignal(externalSignal, config.timeoutMs);

  try {
    const res = await fetch(url.toString(), {
      signal,
      headers: { Accept: "application/json", "User-Agent": "pi-ddgs/1.0" },
    });

    if (!res.ok) throw new Error(`DDGS API returned ${res.status}`);

    const data = await res.json();

    const results: SearchResult[] = (data.results || [])
      .slice(0, limit || config.maxResults)
      .map((r: any) => ({
        title: r.title || "Untitled",
        link: r.link || "",
        snippet: r.snippet || "",
      }));

    return { results };
  } finally {
    cancel();
  }
}

export interface FetchResponse {
  title: string;
  url: string;
  text: string;
  error?: string;
  rendered?: boolean;
  engine?: RenderEngine;
}

export async function fetchPage(
  url: string,
  render = false,
  engine: RenderEngine = "chrome",
  externalSignal?: AbortSignal,
): Promise<FetchResponse> {
  const config = loadConfig();
  const apiUrl = new URL(`${config.ddgsApiUrl}/fetch`);

  apiUrl.searchParams.set("url", url);
  if (render) {
    apiUrl.searchParams.set("render", "true");
    apiUrl.searchParams.set("engine", engine);
  }

  // Headless rendering is much slower than a static GET. Camoufox slower still.
  const renderMultiplier = engine === "camoufox" ? 5 : 3;
  const timeoutMs = render ? config.fetchTimeoutMs * renderMultiplier : config.fetchTimeoutMs;

  const { signal, cancel } = makeSignal(externalSignal, timeoutMs);

  try {
    const res = await fetch(apiUrl.toString(), {
      signal,
      headers: { Accept: "application/json", "User-Agent": "pi-ddgs/1.0" },
    });

    if (!res.ok) throw new Error(`Fetch API returned ${res.status}`);

    const data = await res.json();
    return {
      title: data.title || url,
      url: data.url || url,
      text: data.text || "",
      error: data.error || undefined,
      rendered: data.rendered === true,
      engine: data.engine,
    };
  } finally {
    cancel();
  }
}

export async function searchNews(query: string, limit?: number, externalSignal?: AbortSignal): Promise<SearchResponse> {
  const config = loadConfig();
  const url = new URL(`${config.ddgsApiUrl}/search/news`);

  url.searchParams.set("q", query);
  url.searchParams.set("max_results", String(limit || config.maxResults));
  url.searchParams.set("safesearch", config.safesearch);
  url.searchParams.set("region", config.region);

  const { signal, cancel } = makeSignal(externalSignal, config.timeoutMs);

  try {
    const res = await fetch(url.toString(), {
      signal,
      headers: { Accept: "application/json", "User-Agent": "pi-ddgs/1.0" },
    });

    if (!res.ok) throw new Error(`DDGS News API returned ${res.status}`);

    const data = await res.json();

    const results: SearchResult[] = (data.results || [])
      .slice(0, limit || config.maxResults)
      .map((r: any) => ({
        title: r.title || "Untitled",
        link: r.link || "",
        snippet: r.snippet || "",
      }));

    return { results };
  } finally {
    cancel();
  }
}
