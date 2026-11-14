"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatSigned } from "@/lib/format";
import { getSignals } from "@/lib/market-api";
import type { Signal } from "@/lib/types";

const SENTIMENT = "SENTIMENT";

interface NewsHeadline {
  title: string;
  url: string | null;
  publisher: string | null;
  source: string | null;
  published: string | null;
}

interface Sentiment {
  label: "bullish" | "neutral" | "bearish";
  score: number;
  confidence: number | null;
  summary: string;
  headlines: NewsHeadline[];
  asOf: string;
}

const LABEL_TONE: Record<Sentiment["label"], string> = {
  bullish: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-400/20",
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-400/20",
  bearish: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950/50 dark:text-red-300 dark:ring-red-400/20",
};

const SOURCE_NAME: Record<string, string> = { google_news: "Google News", yahoo_finance: "Yahoo Finance" };

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

function toSentiment(signal: Signal): Sentiment {
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

/** Latest news sentiment for a stock and the headlines it was scored from. */
export function SentimentPanel({ symbol }: { symbol: string }) {
  // Scored once per company (on NSE when listed there), so look it up by symbol on any exchange.
  const latest = useAsync(`sentiment:${symbol}`, (signal) =>
    getSignals({ symbol, signal_type: SENTIMENT, limit: 1 }, signal),
  );

  return (
    <section aria-labelledby="sentiment-heading" className="space-y-3">
      <h2 id="sentiment-heading" className="text-lg font-semibold">
        News sentiment
      </h2>
      {latest.error ? (
        <ErrorState title="Couldn't load news sentiment" error={latest.error} />
      ) : !latest.data ? (
        <LoadingState label="Loading news sentiment…" />
      ) : latest.data.length === 0 ? (
        <EmptyState title={`No news sentiment for ${symbol} yet`} description="It is scored every morning at 7:30 IST." />
      ) : (
        <SentimentCard sentiment={toSentiment(latest.data[0])} />
      )}
    </section>
  );
}

function SentimentCard({ sentiment: s }: { sentiment: Sentiment }) {
  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className={`rounded-md px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset ${LABEL_TONE[s.label]}`}>
          {s.label}
        </span>
        <span className="font-medium tabular-nums">{formatSigned(s.score)}</span>
        {s.confidence != null ? (
          <span className="text-zinc-500 dark:text-zinc-400">confidence {Math.round(s.confidence * 100)}%</span>
        ) : null}
        <span className="text-zinc-500 dark:text-zinc-400">· {formatDate(s.asOf)}</span>
      </div>
      {s.summary ? <p className="text-sm text-zinc-700 dark:text-zinc-300">{s.summary}</p> : null}
      {s.headlines.length > 0 ? (
        <div className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Headlines behind this score ({s.headlines.length})
          </h3>
          <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
            {s.headlines.map((h, i) => (
              <li key={`${i}-${h.title}`} className="py-2">
                {h.url ? (
                  <a href={h.url} target="_blank" rel="noopener noreferrer nofollow" className="hover:underline">
                    {h.title}
                  </a>
                ) : (
                  <span>{h.title}</span>
                )}
                <HeadlineMeta headline={h} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Scored by an AI model from public headlines; it can misread them. Not investment advice.
      </p>
    </div>
  );
}

function HeadlineMeta({ headline: h }: { headline: NewsHeadline }) {
  const parts = [h.publisher, h.source ? (SOURCE_NAME[h.source] ?? h.source) : null, h.published ? formatDate(h.published) : null];
  const text = parts.filter(Boolean).join(" · ");
  return text ? <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{text}</div> : null;
}
