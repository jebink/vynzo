"use client";

import { useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, humanizeSignalType } from "@/lib/format";
import { getSignals, getSignalTypes } from "@/lib/market-api";
import { HIGH_VOLUME_BUY, type Exchange } from "@/lib/types";
import { SignalsTable } from "./signals-table";

type ExchangeFilter = Exchange | "ALL";

const EXCHANGE_OPTIONS = [
  { value: "ALL", label: "All" },
  { value: "NSE", label: "NSE" },
  { value: "BSE", label: "BSE" },
] as const;

const FEED_LIMIT = 100;
const ALL_TYPES = "";

/** The market-wide signal feed with type and exchange filters. */
export function SignalFeed() {
  const types = useAsync("signal-types", (signal) => getSignalTypes(signal));
  // undefined = not chosen yet: default to HIGH_VOLUME_BUY once the types are known.
  const [chosenType, setChosenType] = useState<string | undefined>(undefined);
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");

  const typesSettled = !types.loading;
  const signalType =
    chosenType ??
    (types.data?.some((t) => t.signal_type === HIGH_VOLUME_BUY) ? HIGH_VOLUME_BUY : ALL_TYPES);
  const params = {
    signal_type: signalType || undefined,
    exchange: exchange === "ALL" ? undefined : exchange,
    limit: FEED_LIMIT,
  };
  const feed = useAsync(typesSettled ? `signals:${JSON.stringify(params)}` : null, (signal) =>
    getSignals(params, signal),
  );
  const selectedSummary = types.data?.find((t) => t.signal_type === signalType);

  return (
    <section aria-labelledby="signal-feed-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="signal-feed-heading" className="text-lg font-semibold">
            Signal feed
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Latest signals across NSE and BSE, newest first.
            {selectedSummary?.latest_as_of
              ? ` Latest ${humanizeSignalType(selectedSummary.signal_type).toLowerCase()} signal: ${formatDate(selectedSummary.latest_as_of)}.`
              : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            Signal type
            <select
              value={signalType}
              disabled={!typesSettled}
              onChange={(event) => setChosenType(event.target.value)}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            >
              <option value={ALL_TYPES}>All types</option>
              {types.data?.map((t) => (
                <option key={t.signal_type} value={t.signal_type}>
                  {humanizeSignalType(t.signal_type)} ({t.count})
                </option>
              ))}
            </select>
          </label>
          <SegmentedControl
            label="Exchange"
            options={EXCHANGE_OPTIONS}
            value={exchange}
            onChange={setExchange}
          />
        </div>
      </div>

      {types.error ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Couldn&apos;t load signal types; showing all types.
        </p>
      ) : null}

      {feed.error ? (
        <ErrorState title="Couldn't load signals" error={feed.error} />
      ) : !feed.data ? (
        <LoadingState label="Loading signals…" />
      ) : feed.data.length === 0 ? (
        <EmptyState
          title="No signals match these filters"
          description="Try another signal type or exchange."
        />
      ) : (
        <>
          <SignalsTable signals={feed.data} />
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Showing {feed.data.length} signal{feed.data.length === 1 ? "" : "s"}
            {feed.data.length === FEED_LIMIT ? ` (the latest ${FEED_LIMIT})` : ""}.
          </p>
        </>
      )}
    </section>
  );
}
