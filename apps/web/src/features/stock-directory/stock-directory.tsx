"use client";

import Link from "next/link";
import { useId, useMemo, useState } from "react";
import { CAP_OPTIONS, type CapFilter, matchesCompany, SectorSelect } from "@/components/company-filters";
import { ExchangeBadge } from "@/components/exchange-badge";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatPrice, formatSigned, formatVolume } from "@/lib/format";
import { getOverview } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import type { Exchange, StockSnapshot } from "@/lib/types";
import { Sparkline } from "./sparkline";

/** About three months of trading sessions per sparkline. */
const SPARKLINE_POINTS = 60;

type ExchangeFilter = "ALL" | Exchange;
type SortKey = "symbol" | "gainers" | "losers" | "volume";

const EXCHANGE_OPTIONS = [
  { value: "ALL", label: "All" },
  { value: "NSE", label: "NSE" },
  { value: "BSE", label: "BSE" },
] as const;

const SORT_OPTIONS = [
  { value: "symbol", label: "A–Z" },
  { value: "gainers", label: "Top gainers" },
  { value: "losers", label: "Top losers" },
  { value: "volume", label: "Volume" },
] as const;

/** Nulls always sort last, whatever the direction. */
function byNumber(pick: (s: StockSnapshot) => number | null, descending: boolean) {
  return (a: StockSnapshot, b: StockSnapshot) => {
    const x = pick(a);
    const y = pick(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return descending ? y - x : x - y;
  };
}

const SORTERS: Record<SortKey, (a: StockSnapshot, b: StockSnapshot) => number> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol) || a.exchange.localeCompare(b.exchange),
  gainers: byNumber((s) => s.change_pct, true),
  losers: byNumber((s) => s.change_pct, false),
  volume: byNumber((s) => s.volume, true),
};

/** Every ingested stock with its last close, day change, volume and a 3-month sparkline. */
export function StockDirectory() {
  const inputId = useId();
  const [text, setText] = useState("");
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const [sort, setSort] = useState<SortKey>("symbol");
  const [cap, setCap] = useState<CapFilter>("all");
  const [sector, setSector] = useState<string>("any");

  const overview = useAsync("overview", (signal) =>
    getOverview({ points: SPARKLINE_POINTS }, signal),
  );

  const stocks = useMemo(() => {
    const all = overview.data?.stocks ?? [];
    const needle = text.trim().toUpperCase();
    return all
      .filter((s) => exchange === "ALL" || s.exchange === exchange)
      .filter((s) => matchesCompany(s, cap, sector))
      .filter(
        (s) =>
          !needle ||
          s.symbol.includes(needle) ||
          (s.company_name ?? "").toUpperCase().includes(needle),
      )
      .sort(SORTERS[sort]);
  }, [overview.data, text, exchange, sort, cap, sector]);

  const total = overview.data?.stocks.length ?? 0;
  const advancing = overview.data?.stocks.filter((s) => (s.change_pct ?? 0) > 0).length ?? 0;
  const declining = overview.data?.stocks.filter((s) => (s.change_pct ?? 0) < 0).length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Stocks</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            {overview.data
              ? `${total} stocks ingested · last close ${formatDate(overview.data.as_of)} · `
              : "Every stock with ingested price data. "}
            {overview.data ? (
              <>
                <span className="text-green-600 dark:text-green-500">{advancing} up</span>
                {", "}
                <span className="text-red-600 dark:text-red-500">{declining} down</span>
              </>
            ) : null}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={inputId} className="sr-only">
          Filter stocks
        </label>
        <input
          id={inputId}
          type="search"
          autoComplete="off"
          placeholder="Filter by symbol or company…"
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="w-full max-w-xs rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none placeholder:text-zinc-400 focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:placeholder:text-zinc-500 dark:focus:border-zinc-500 dark:focus:ring-zinc-800"
        />
        <SegmentedControl label="Exchange" options={EXCHANGE_OPTIONS} value={exchange} onChange={setExchange} />
        <SegmentedControl label="Market cap" options={CAP_OPTIONS} value={cap} onChange={setCap} />
        <SectorSelect items={overview.data?.stocks ?? []} value={sector} onChange={setSector} />
        <SegmentedControl label="Sort by" options={SORT_OPTIONS} value={sort} onChange={setSort} />
      </div>

      {overview.error ? (
        <ErrorState title="Couldn't load stocks" error={overview.error} />
      ) : !overview.data ? (
        <LoadingState label="Loading stocks…" />
      ) : stocks.length === 0 ? (
        <EmptyState
          title={total === 0 ? "No stocks ingested yet" : "No stocks match this filter"}
          description={total === 0 ? "Run the EOD ingestion job to load price data." : undefined}
        />
      ) : (
        <StockTable stocks={stocks} points={overview.data.points} />
      )}
    </div>
  );
}

function StockTable({ stocks, points }: { stocks: StockSnapshot[]; points: number }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Stock</th>
            <th scope="col" className="px-3 py-2 font-medium">Last {points} sessions</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Close</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Change</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Volume</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">As of</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {stocks.map((stock) => (
            <StockRow key={stock.listing_id} stock={stock} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockRow({ stock }: { stock: StockSnapshot }) {
  const href = stockHref(stock.exchange, stock.symbol);
  const change = stock.change_pct;
  const tone =
    change == null || change === 0
      ? "text-zinc-500 dark:text-zinc-400"
      : change > 0
        ? "text-green-600 dark:text-green-500"
        : "text-red-600 dark:text-red-500";

  return (
    <tr className="hover:bg-zinc-50 dark:hover:bg-zinc-900/60">
      <td className="max-w-[260px] px-3 py-2">
        <Link href={href} className="group block focus:outline-none">
          <span className="flex items-center gap-2">
            <span className="font-semibold group-hover:underline group-focus-visible:underline">
              {stock.symbol}
            </span>
            <ExchangeBadge exchange={stock.exchange} />
            {stock.kind === "index" ? (
              <span className="text-[10px] uppercase tracking-wide text-zinc-400">Index</span>
            ) : null}
          </span>
          <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400">
            {stock.company_name ?? "—"}
          </span>
        </Link>
      </td>
      <td className="px-3 py-2">
        <Link href={href} tabIndex={-1} aria-hidden>
          <Sparkline values={stock.closes} label={`${stock.symbol} closing prices`} />
        </Link>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatPrice(stock.close)}</td>
      <td className={`px-3 py-2 text-right font-medium tabular-nums ${tone}`}>
        {change == null ? "—" : `${formatSigned(change)}%`}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatVolume(stock.volume)}</td>
      <td className="px-3 py-2 text-right text-xs text-zinc-500 tabular-nums dark:text-zinc-400">
        {formatDate(stock.latest_ts)}
      </td>
    </tr>
  );
}
