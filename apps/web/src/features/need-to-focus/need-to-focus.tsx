"use client";

import Link from "next/link";
import { ExchangeBadge } from "@/components/exchange-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatPrice, formatSigned } from "@/lib/format";
import { getFocus } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import type { FocusPart, FocusResponse } from "@/lib/types";

type FocusStock = NonNullable<FocusResponse["stock"]>;

const GRADE_STYLE: Record<FocusStock["grade"], string> = {
  A: "bg-red-600 text-white",
  B: "bg-amber-500 text-white",
  C: "bg-sky-600 text-white",
  D: "bg-zinc-400 text-white dark:bg-zinc-600",
};

const GRADE_MEANING: Record<FocusStock["grade"], string> = {
  A: "Major: act on it today",
  B: "High: look at it today",
  C: "Moderate: worth a look",
  D: "Quiet market: nothing major",
};

const PARTS: { key: keyof FocusStock["parts"]; label: string }[] = [
  { key: "news", label: "News" },
  { key: "market", label: "Market move" },
  { key: "event", label: "Upcoming event" },
];

const EVENT_LABEL: Record<string, string> = { results: "Quarterly results", ex_dividend: "Ex-dividend" };

/** Dashboard: the single stock that most needs attention, with its focus grade and why. */
export function NeedToFocus() {
  const focus = useAsync("focus", (signal) => getFocus(signal));
  return (
    <section aria-labelledby="focus-heading" className="space-y-3">
      <h2 id="focus-heading" className="text-lg font-semibold">
        Need to focus
      </h2>
      {focus.error ? (
        <ErrorState title="Couldn't load the focus stock" error={focus.error} />
      ) : !focus.data ? (
        <LoadingState label="Finding the stock that needs attention…" />
      ) : !focus.data.stock ? (
        <EmptyState title="Nothing to focus on yet" description="No recent prices, news or events." />
      ) : (
        <FocusCard stock={focus.data.stock} asOf={focus.data.as_of} />
      )}
    </section>
  );
}

function FocusCard({ stock, asOf }: { stock: FocusStock; asOf: string | null }) {
  const p = stock.performance;
  return (
    <article className="grid gap-5 rounded-lg border border-zinc-200 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] dark:border-zinc-800">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Link href={stockHref(stock.exchange, stock.symbol)} className="group flex items-center gap-2">
              <span className="text-xl font-semibold group-hover:underline">{stock.symbol}</span>
              <ExchangeBadge exchange={stock.exchange} />
            </Link>
            <p className="truncate text-sm text-zinc-600 dark:text-zinc-400">
              {stock.company_name ?? "—"}
              {stock.sector ? ` · ${stock.sector}` : ""}
            </p>
          </div>
          <div className="text-center">
            <span
              className={`inline-flex size-12 items-center justify-center rounded-lg text-2xl font-bold ${GRADE_STYLE[stock.grade]}`}
              aria-label={`Focus grade ${stock.grade}`}
            >
              {stock.grade}
            </span>
            <p className="mt-1 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">{stock.score}/100</p>
          </div>
        </div>
        <p className="text-sm font-medium">{GRADE_MEANING[stock.grade]}</p>

        <div className="space-y-2.5">
          {PARTS.map(({ key, label }) => (
            <PartBar key={key} label={label} part={stock.parts[key]} />
          ))}
        </div>

        <dl className="grid grid-cols-4 gap-2 text-sm">
          <Stat label="Close" value={formatPrice(p.close)} />
          <Stat label="1 day" value={pct(p.change_1d_pct)} tone={p.change_1d_pct} />
          <Stat label="5 days" value={pct(p.change_5d_pct)} tone={p.change_5d_pct} />
          <Stat label="20 days" value={pct(p.change_20d_pct)} tone={p.change_20d_pct} />
        </dl>
      </div>

      <div className="space-y-4 text-sm">
        {stock.event ? (
          <div className="rounded-md bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <span className="font-semibold">{EVENT_LABEL[stock.event.type] ?? stock.event.type}</span> on{" "}
            {formatDate(stock.event.date)} ({stock.event.days_away === 0 ? "today" : `in ${stock.event.days_away} days`})
          </div>
        ) : null}
        {stock.news ? (
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              In the news · {stock.news.headline_count} headlines · {stock.news.label ?? "neutral"}
            </h3>
            {stock.news.summary ? <p className="text-zinc-700 dark:text-zinc-300">{stock.news.summary}</p> : null}
            <ul className="space-y-1.5">
              {stock.news.headlines.map((h) => (
                <li key={h.url}>
                  <a
                    href={h.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="line-clamp-2 text-sky-700 hover:underline dark:text-sky-400"
                  >
                    {h.title}
                  </a>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {h.publisher ?? h.source}
                    {h.published ? ` · ${formatDate(h.published)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-zinc-500 dark:text-zinc-400">No recent headlines.</p>
        )}
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Grade from news buzz, how unusual the recent move is for this stock, and events in the next two
          weeks{asOf ? ` · prices as of ${formatDate(asOf)}` : ""}. Not investment advice.
        </p>
      </div>
    </article>
  );
}

function PartBar({ label, part }: { label: string; part: FocusPart }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
          {Math.round(part.points)}/{part.max}
        </span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800" aria-hidden>
        <div className="h-full rounded-full bg-sky-600 dark:bg-sky-400" style={{ width: `${(part.points / part.max) * 100}%` }} />
      </div>
      <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">{part.reason}</p>
    </div>
  );
}

const pct = (v: number | null) => (v == null ? "—" : `${formatSigned(v, 1)}%`);

function Stat({ label, value, tone }: { label: string; value: string; tone?: number | null }) {
  const color =
    tone == null || tone === 0 ? "" : tone > 0 ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500";
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className={`font-semibold tabular-nums ${color}`}>{value}</dd>
    </div>
  );
}
