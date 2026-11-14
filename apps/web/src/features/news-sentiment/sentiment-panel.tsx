"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatSigned } from "@/lib/format";
import { getSignals } from "@/lib/market-api";
import { LABEL_TONE, SENTIMENT, SOURCE_NAME, toSentiment, type NewsHeadline, type Sentiment } from "./sentiment";

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
        <EmptyState title={`No news sentiment for ${symbol} yet`} description="It is rescored every 3 hours." />
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
