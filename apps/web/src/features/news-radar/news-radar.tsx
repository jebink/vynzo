"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ExchangeBadge } from "@/components/exchange-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatSigned } from "@/lib/format";
import { getSignals } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import type { Exchange, Signal } from "@/lib/types";
import { LABEL_TONE, SENTIMENT, toSentiment, type Sentiment } from "@/features/news-sentiment/sentiment";

import { rankByRelevance } from "./relevance";

const REFRESH_MS = 60_000;
const SHOWN = 12;
// shortcut: one scan day is ~255 rows, so 500 covers it client-side; add a server-side "latest day" filter if the universe passes 500.
const FETCH_LIMIT = 500;

interface NewsItem extends Sentiment {
  id: number;
  exchange: Exchange;
  symbol: string;
  companyName: string | null;
  latest: string | null;
}

function toItem(signal: Signal): NewsItem {
  const s = toSentiment(signal);
  const latest = s.headlines.map((h) => h.published).filter((p) => p !== null).sort().at(-1) ?? null;
  return {
    ...s,
    id: signal.id,
    exchange: signal.exchange as Exchange,
    symbol: signal.symbol,
    companyName: signal.company_name,
    latest,
  };
}

/** Rows of the newest scan day that actually had news (no-news rows carry confidence 0). */
function latestScan(rows: Signal[]): NewsItem[] {
  const day = rows.reduce((max, r) => (r.as_of > max ? r.as_of : max), "");
  return rankByRelevance(rows.filter((r) => r.as_of === day).map(toItem).filter((i) => (i.confidence ?? 0) > 0));
}

/** Dashboard: latest news per stock, ranked by relevance, refreshed every minute. */
export function NewsRadar() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const scan = useAsync(`news-radar:${tick}`, (signal) =>
    getSignals({ signal_type: SENTIMENT, limit: FETCH_LIMIT }, signal),
  );
  // Keep showing the previous scan while a refresh is in flight.
  const [rows, setRows] = useState<Signal[] | null>(null);
  if (scan.data && scan.data !== rows) setRows(scan.data);
  const shown = useMemo(() => (rows ? latestScan(rows) : null), [rows]);

  return (
    <section aria-labelledby="news-radar-heading" className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="news-radar-heading" className="text-lg font-semibold">
            Market news radar
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {scan.error ? "Scanning paused" : "Scanning"} · news rescored every 3 hours
            {shown?.[0] ? ` · last scan ${formatDate(shown[0].asOf)}` : ""}
          </p>
        </div>
        <Radar active={!scan.error} />
      </div>
      {scan.error && !shown ? (
        <ErrorState title="Couldn't load market news" error={scan.error} />
      ) : !shown ? (
        <LoadingState label="Scanning market news…" />
      ) : shown.length === 0 ? (
        <EmptyState title="No market news yet" description="Stocks appear here once the next news scan scores them." />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {shown.slice(0, SHOWN).map((item) => (
            <li key={item.id}>
              <NewsCard item={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function NewsCard({ item }: { item: NewsItem }) {
  const top = item.headlines[0];
  return (
    <article className="flex h-full flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <Link href={stockHref(item.exchange, item.symbol)} className="flex items-center gap-3 hover:opacity-80">
        <StockMonogram symbol={item.symbol} />
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold">{item.symbol}</span>
            <ExchangeBadge exchange={item.exchange} />
          </div>
          {item.companyName ? (
            <div className="truncate text-sm text-zinc-500 dark:text-zinc-400">{item.companyName}</div>
          ) : null}
        </div>
      </Link>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`rounded-md px-2 py-0.5 text-xs font-medium capitalize ring-1 ring-inset ${LABEL_TONE[item.label]}`}>
          {item.label}
        </span>
        <span className="font-medium tabular-nums">{formatSigned(item.score)}</span>
        {item.confidence != null ? (
          <span className="text-zinc-500 dark:text-zinc-400">confidence {Math.round(item.confidence * 100)}%</span>
        ) : null}
      </div>
      {item.summary ? <p className="text-sm text-zinc-700 dark:text-zinc-300">{item.summary}</p> : null}
      {top ? (
        <div className="mt-auto border-t border-zinc-100 pt-2 text-sm dark:border-zinc-800">
          {top.url ? (
            <a href={top.url} target="_blank" rel="noopener noreferrer nofollow" className="line-clamp-2 hover:underline">
              {top.title}
            </a>
          ) : (
            <span className="line-clamp-2">{top.title}</span>
          )}
          <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {[top.publisher, top.published ? formatDate(top.published) : null].filter(Boolean).join(" · ")}
          </div>
        </div>
      ) : null}
    </article>
  );
}

/** Large initials tile; the hue is derived from the symbol so each stock keeps its colour. */
function StockMonogram({ symbol }: { symbol: string }) {
  const hue = [...symbol].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <span
      aria-hidden
      className="flex size-14 shrink-0 items-center justify-center rounded-xl text-lg font-bold text-white"
      style={{ backgroundColor: `hsl(${hue} 55% 42%)` }}
    >
      {symbol.replace(/[^A-Z0-9]/gi, "").slice(0, 2).toUpperCase()}
    </span>
  );
}

/** CSS-only radar: a rotating sweep over rings with pinging blips. Still when reduced motion is on. */
function Radar({ active }: { active: boolean }) {
  return (
    <div
      role="img"
      aria-label={active ? "Scanning market news" : "Scanning paused"}
      className="relative size-20 shrink-0 overflow-hidden rounded-full border border-emerald-500/40 bg-emerald-950/90"
    >
      <div className="absolute inset-[22%] rounded-full border border-emerald-500/30" />
      <div className="absolute inset-[44%] rounded-full bg-emerald-400/60" />
      {active ? (
        <>
          <div className="absolute inset-0 animate-spin rounded-full bg-[conic-gradient(from_0deg,transparent_0deg,transparent_270deg,rgb(52_211_153/0.7)_360deg)] [animation-duration:3s] motion-reduce:animate-none" />
          <span className="absolute left-[28%] top-[24%] size-2 animate-ping rounded-full bg-emerald-300 motion-reduce:animate-none" />
          <span className="absolute bottom-[26%] right-[22%] size-2 animate-ping rounded-full bg-emerald-300 [animation-delay:1.2s] motion-reduce:animate-none" />
        </>
      ) : null}
    </div>
  );
}
