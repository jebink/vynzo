"use client";

import { useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatSigned } from "@/lib/format";
import { getOpportunityPerformance } from "@/lib/market-api";
import type { Horizon, OutcomeStatus, PerformanceResponse, PickStatusFilter } from "@/lib/types";

const STATUS_OPTIONS = [
  { value: "actionable", label: "Actionable" },
  { value: "watch", label: "Monitor-only" },
  { value: "all", label: "All picks" },
] as const;

const STATUS_LABEL: Record<OutcomeStatus, string> = {
  target_hit: "Target hit",
  stopped: "Stopped out",
  expired: "Expired",
  not_triggered: "Not triggered",
};

const pct = (value: number | null) => (value == null ? "—" : `${Math.round(value * 100)}%`);
const ret = (value: number | null) => (value == null ? "—" : `${formatSigned(value, 1)}%`);

/** How past picks of one horizon played out: hit rate, returns, score bands, latest results. */
export function PerformancePanel({ horizon }: { horizon: Horizon }) {
  const [status, setStatus] = useState<PickStatusFilter>("actionable");
  const perf = useAsync(`opportunity-performance:${status}`, (signal) =>
    getOpportunityPerformance(status, signal),
  );

  return (
    <div className="space-y-4">
      <SegmentedControl label="Picks" options={STATUS_OPTIONS} value={status} onChange={setStatus} />
      {perf.error ? (
        <ErrorState title="Couldn't load the track record" error={perf.error} />
      ) : !perf.data ? (
        <LoadingState label="Loading track record…" />
      ) : (
        <TrackRecord data={perf.data} horizon={horizon} />
      )}
    </div>
  );
}

function TrackRecord({ data, horizon }: { data: PerformanceResponse; horizon: Horizon }) {
  const stats = data.horizons[horizon];
  const recent = data.recent.filter((pick) => pick.horizon === horizon).slice(0, 10);
  const closed = Object.values(stats.closed).reduce((a, b) => a + b, 0);

  if (closed === 0) {
    return (
      <EmptyState
        title="No closed picks yet"
        description={`${stats.picks} picks so far, ${stats.open} still open. Results appear here once picks reach their target, stop-loss or time limit.`}
      />
    );
  }

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Hit rate" value={pct(stats.hit_rate)} hint="Targets hit, of picks that were entered" />
        <Tile label="Average return" value={ret(stats.avg_return_pct)} hint="Per entered pick, direction-adjusted" />
        <Tile label="Closed" value={String(closed)} hint={`${stats.closed.not_triggered} never triggered`} />
        <Tile label="Open" value={String(stats.open)} hint="Still inside their holding period" />
      </dl>

      <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full min-w-[420px] text-sm">
          <caption className="sr-only">Results by score band</caption>
          <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Score</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Entered</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Hit rate</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Avg return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 tabular-nums dark:divide-zinc-800">
            {stats.by_score.map((band) => (
              <tr key={band.band}>
                <td className="px-3 py-2">{band.band}</td>
                <td className="px-3 py-2 text-right">{band.triggered}</td>
                <td className="px-3 py-2 text-right">{pct(band.hit_rate)}</td>
                <td className="px-3 py-2 text-right">{ret(band.avg_return_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {recent.length ? (
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Latest results
          </h3>
          <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 text-sm dark:divide-zinc-800 dark:border-zinc-800">
            {recent.map((pick) => (
              <li key={pick.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span>
                  <span className={pick.direction === "BUY" ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}>
                    {pick.direction}
                  </span>{" "}
                  <span className="font-medium">{pick.symbol}</span>{" "}
                  <span className="text-zinc-500 dark:text-zinc-400">
                    picked {formatDate(pick.as_of)} · score {pick.score}
                  </span>
                </span>
                <span className="tabular-nums">
                  {STATUS_LABEL[pick.status]} {pick.return_pct != null ? `(${ret(pick.return_pct)})` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
      <dd className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{hint}</dd>
    </div>
  );
}
