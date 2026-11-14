// Parsing and styling of SENTIMENT signal rows, shared by the stock page and the dashboard radar.

import type { Signal } from "@/lib/types";

export const SENTIMENT = "SENTIMENT";

export interface NewsHeadline {
  title: string;
  url: string | null;
  publisher: string | null;
  source: string | null;
  published: string | null;
}

export interface Sentiment {
  label: "bullish" | "neutral" | "bearish";
  score: number;
  confidence: number | null;
  summary: string;
  headlines: NewsHeadline[];
  asOf: string;
}

export const LABEL_TONE: Record<Sentiment["label"], string> = {
  bullish: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-400/20",
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-400/20",
  bearish: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950/50 dark:text-red-300 dark:ring-red-400/20",
};

export const SOURCE_NAME: Record<string, string> = { google_news: "Google News", yahoo_finance: "Yahoo Finance" };

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

/** Only http(s) links are rendered; anything else from a feed is shown as plain text. */
const safeHref = (v: unknown): string | null => {
  const url = str(v);
  return url && /^https?:\/\//i.test(url) ? url : null;
};

function toHeadline(raw: unknown): NewsHeadline | null {
  // Rows from the old system stored bare title strings.
  if (typeof raw === "string") return raw ? { title: raw, url: null, publisher: null, source: null, published: null } : null;
  if (!raw || typeof raw !== "object") return null;
  const h = raw as Record<string, unknown>;
  const title = str(h.title);
  return title
    ? { title, url: safeHref(h.url), publisher: str(h.publisher), source: str(h.source), published: str(h.published) }
    : null;
}

export function toSentiment(signal: Signal): Sentiment {
  const meta = signal.meta ?? {};
  const label = meta.label === "bullish" || meta.label === "bearish" ? meta.label : "neutral";
  const headlines = Array.isArray(meta.headlines) ? meta.headlines.map(toHeadline).filter((h) => h !== null) : [];
  return {
    label,
    score: signal.strength ?? 0,
    confidence: typeof meta.confidence === "number" ? meta.confidence : null,
    summary: str(meta.summary) ?? "",
    headlines,
    asOf: signal.as_of,
  };
}
