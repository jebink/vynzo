"use client";

import Link from "next/link";

import { ExchangeBadge } from "@/components/exchange-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate } from "@/lib/format";
import { getUpcomingEvents } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import type { CorporateEvent } from "@/lib/types";

const DAYS = 90; // results seasons are 6-10 weeks out for most of the quarter

const TYPE: Record<CorporateEvent["event_type"], { label: string; tone: string }> = {
  results: {
    label: "Results",
    tone: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-400/20",
  },
  ex_dividend: {
    label: "Ex-dividend",
    tone: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950/50 dark:text-amber-300 dark:ring-amber-400/20",
  },
};

function detail(e: CorporateEvent): string | null {
  const d = e.details;
  if (e.event_type === "ex_dividend") return d.amount ? `₹${d.amount} per share` : null;
  const parts = [
    d.window_end ? `expected by ${formatDate(d.window_end)}` : null,
    d.eps_estimate != null ? `EPS est. ₹${d.eps_estimate}` : null,
  ];
  return parts.filter(Boolean).join(" · ") || null;
}

/** Dashboard side panel: upcoming quarterly results and ex-dividend dates, grouped by day. */
export function UpcomingEvents() {
  const events = useAsync("upcoming-events", (signal) => getUpcomingEvents({ days: DAYS, limit: 500 }, signal));

  const byDay = new Map<string, CorporateEvent[]>();
  for (const e of events.data ?? []) byDay.set(e.event_date, [...(byDay.get(e.event_date) ?? []), e]);

  return (
    <section aria-labelledby="upcoming-events-heading" className="space-y-3">
      <div>
        <h2 id="upcoming-events-heading" className="text-lg font-semibold">
          Upcoming events
        </h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">Results and dividends, next {DAYS} days</p>
      </div>
      {events.error ? (
        <ErrorState title="Couldn't load upcoming events" error={events.error} />
      ) : !events.data ? (
        <LoadingState label="Loading upcoming events…" />
      ) : byDay.size === 0 ? (
        <EmptyState title="No upcoming events" description="The events calendar refreshes every morning." />
      ) : (
        <ol className="max-h-[48rem] space-y-4 overflow-y-auto rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          {[...byDay].map(([day, list]) => (
            <li key={day}>
              <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                {formatDate(day)}
              </h3>
              <ul className="mt-1.5 divide-y divide-zinc-100 dark:divide-zinc-800">
                {list.map((e) => (
                  <li key={`${e.exchange}:${e.symbol}:${e.event_type}`} className="py-2 text-sm">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TYPE[e.event_type].tone}`}>
                        {TYPE[e.event_type].label}
                      </span>
                      <Link href={stockHref(e.exchange, e.symbol)} className="font-medium hover:underline">
                        {e.symbol}
                      </Link>
                      <ExchangeBadge exchange={e.exchange} />
                    </div>
                    {e.company_name || detail(e) ? (
                      <div className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">
                        {[e.company_name, detail(e)].filter(Boolean).join(" · ")}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
