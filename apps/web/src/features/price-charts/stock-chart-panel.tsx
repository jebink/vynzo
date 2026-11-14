"use client";

import { useMemo, useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { getBars, getIndicators, getSignals, getSwingSignals } from "@/lib/market-api";
import { tradingDate } from "@/lib/format";
import { HIGH_VOLUME_BUY, type Exchange, type Timeframe } from "@/lib/types";
import { PriceChart, type ChartMarker, type PriceChartData } from "./price-chart";

type ChartRange = "1D" | "1W" | "1M";

const RANGES: Record<ChartRange, { timeframe: Timeframe; initialBars: number }> = {
  "1D": { timeframe: "1d", initialBars: 180 },
  "1W": { timeframe: "1w", initialBars: 156 },
  "1M": { timeframe: "1mo", initialBars: 120 },
};

const RANGE_OPTIONS = [
  { value: "1D", label: "1D" },
  { value: "1W", label: "1W" },
  { value: "1M", label: "1M" },
] as const;

const BAR_LIMIT = 500;
const MARKER_LIMIT = 500;

/** Timeframe toggle plus the price chart; EMA/RSI overlays and signal markers are daily-only. */
export function StockChartPanel({ exchange, symbol }: { exchange: Exchange; symbol: string }) {
  const [range, setRange] = useState<ChartRange>("1D");
  const { timeframe, initialBars } = RANGES[range];
  const daily = range === "1D";
  const stock = `${exchange}:${symbol}`;

  const bars = useAsync(`bars:${stock}:${timeframe}`, (signal) =>
    getBars(exchange, symbol, { timeframe, limit: BAR_LIMIT }, signal),
  );
  const indicators = useAsync(daily ? `indicators:${stock}` : null, (signal) =>
    getIndicators(exchange, symbol, { limit: BAR_LIMIT }, signal),
  );
  const volumeSignals = useAsync(daily ? `hvb:${stock}` : null, (signal) =>
    getSignals({ exchange, symbol, signal_type: HIGH_VOLUME_BUY, limit: MARKER_LIMIT }, signal),
  );
  const swing = useAsync(daily ? `swing:${stock}` : null, (signal) =>
    getSwingSignals({ exchange, symbol, limit: MARKER_LIMIT }, signal),
  );

  const loading = bars.loading || indicators.loading || volumeSignals.loading || swing.loading;

  const chartData = useMemo<PriceChartData | null>(() => {
    if (!bars.data) return null;
    let markers: ChartMarker[] | null = null;
    if (daily) {
      markers = [];
      for (const s of volumeSignals.data ?? []) {
        markers.push({ time: tradingDate(s.as_of), kind: "HIGH_VOLUME_BUY" });
      }
      for (const s of swing.data ?? []) {
        if (s.signal === "BUY") markers.push({ time: tradingDate(s.as_of), kind: "SWING_BUY" });
        if (s.signal === "SELL") markers.push({ time: tradingDate(s.as_of), kind: "SWING_SELL" });
      }
    }
    return {
      bars: bars.data.bars,
      indicators: daily ? (indicators.data?.rows ?? null) : null,
      markers,
      initialBars,
    };
  }, [bars.data, indicators.data, volumeSignals.data, swing.data, daily, initialBars]);

  const overlayIssues = [
    indicators.error ? "EMA/RSI indicators" : null,
    volumeSignals.error ? "high-volume markers" : null,
    swing.error ? "swing markers" : null,
  ].filter(Boolean);

  return (
    <section aria-labelledby="chart-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="chart-heading" className="text-lg font-semibold">
          Price chart
        </h2>
        <SegmentedControl label="Timeframe" options={RANGE_OPTIONS} value={range} onChange={setRange} />
      </div>

      {bars.error ? (
        <ErrorState title="Couldn't load price bars" error={bars.error} className="h-[440px] content-center" />
      ) : loading || !chartData ? (
        <LoadingState label="Loading chart…" className={`content-center ${daily ? "h-[560px]" : "h-[440px]"}`} />
      ) : chartData.bars.length === 0 ? (
        <EmptyState
          title="No price history yet"
          description={`There are no ${range} bars for ${symbol} on ${exchange}.`}
          className="h-[440px] content-center"
        />
      ) : (
        <PriceChart data={chartData} />
      )}

      {overlayIssues.length > 0 && !loading ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Couldn&apos;t load {overlayIssues.join(", ")}; showing the chart without them.
        </p>
      ) : null}
      {daily ? null : (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          EMA, RSI and signal markers are shown on the 1D chart.
        </p>
      )}
    </section>
  );
}
