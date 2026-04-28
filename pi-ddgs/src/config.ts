import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const CONFIG_PATH = join(homedir(), ".pi", "ddgs.json");

export type SafeSearch = "on" | "moderate" | "off";
export type RenderEngine = "chrome" | "camoufox";

export interface Config {
  ddgsApiUrl: string;
  timeoutMs: number;
  fetchTimeoutMs: number;
  maxResults: number;
  safesearch: SafeSearch;
  region: string;
  defaultEngine: RenderEngine;
  searchCacheSize: number;
}

const DEFAULTS: Config = {
  ddgsApiUrl: process.env.DDG_API_URL || "http://localhost:8091",
  timeoutMs: 30000,
  fetchTimeoutMs: 20000,
  maxResults: 10,
  safesearch: "off",
  region: "us-en",
  defaultEngine: "chrome",
  searchCacheSize: 50,
};

export function loadConfig(): Config {
  try {
    if (existsSync(CONFIG_PATH)) {
      const raw = JSON.parse(readFileSync(CONFIG_PATH, "utf-8"));
      return { ...DEFAULTS, ...raw };
    }
  } catch {}
  return DEFAULTS;
}
