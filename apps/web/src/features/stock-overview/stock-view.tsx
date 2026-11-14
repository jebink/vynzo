"use client";

import Link from "next/link";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { SentimentPanel } from "@/features/news-sentiment/sentiment-panel";
import { StockChartPanel } from "@/features/price-charts/stock-chart-panel";
import { SignalsTable } from "@/features/signals/components/signals-table";
import { useAsync } from "@/hooks/use-async";
import { isNotFound } from "@/lib/api";
import { getListing, getSignals } from "@/lib/market-api";
import type { Exchange } from "@/lib/types";
import { StockHeader, StockHeaderSkeleton } from "./stock-header";

const STOCK_SIGNAL_LIMIT = 50;

/** The stock page body: header, price chart and this stock's signals. */
export function StockView({ exchange, symbol }: { exchange: Exchange; symbol: string }) {
  const stock = `${exchange}:${symbol}`;
  const listing = useAsync(`listing:${stock}`, (signal) => getListing(exchange, symbol, signal));

  if (isNotFound(listing.error)) {
    return <StockNotFound exchange={exchange} symbol={symbol} />;
  }

  return (
    <div className="space-y-8">
      {listing.data ? (
        <StockHeader listing={listing.data} />
      ) : listing.error ? (
        <ErrorState title={`Couldn't load ${symbol}`} error={listing.error} />
      ) : (
        <StockHeaderSkeleton symbol={symbol} exchange={exchange} />
      )}
      <StockChartPanel exchange={exchange} symbol={symbol} />
      <SentimentPanel symbol={symbol} />
      <StockSignals exchange={exchange} symbol={symbol} />
    </div>
  );
}

function StockSignals({ exchange, symbol }: { exchange: Exchange; symbol: string }) {
  const signals = useAsync(`stock-signals:${exchange}:${symbol}`, (signal) =>
    getSignals({ exchange, symbol, limit: STOCK_SIGNAL_LIMIT }, signal),
  );
  return (
    <section aria-labelledby="stock-signals-heading" className="space-y-3">
      <h2 id="stock-signals-heading" className="text-lg font-semibold">
        Signals
      </h2>
      {signals.error ? (
        <ErrorState title="Couldn't load signals" error={signals.error} />
      ) : !signals.data ? (
        <LoadingState label="Loading signals…" />
      ) : signals.data.length === 0 ? (
        <EmptyState title={`No signals for ${symbol} yet`} />
      ) : (
        <SignalsTable signals={signals.data} showInstrument={false} />
      )}
    </section>
  );
}

function StockNotFound({ exchange, symbol }: { exchange: Exchange; symbol: string }) {
  return (
    <div className="mx-auto max-w-md rounded-lg border border-zinc-200 px-6 py-12 text-center dark:border-zinc-800">
      <h1 className="text-xl font-semibold">Stock not found</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        We couldn&apos;t find <span className="font-medium">{symbol}</span> on {exchange}. Check the
        symbol, or try the other exchange.
      </p>
      <Link
        href="/market"
        className="mt-6 inline-flex rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        Go to Market
      </Link>
    </div>
  );
}
