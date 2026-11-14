"use client";

import { useMemo, useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { Switch } from "@/components/switch";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { getBars, getForecast, getIndicators, getSignals, getSwingSignals } from "@/lib/market-api";
import { tradingDate } from "@/lib/format";
import { HIGH_VOLUME_BUY, type Exchange, type Timeframe } from "@/lib/types";
import { PriceChart, type ChartMarker, type PriceChartData, type PriceLevel } from "./price-chart";
import { COMPARE, MODEL_OPTIONS, PredictionLegend, toLine } from "./prediction";

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

/** Timeframe toggle plus the price chart; EMA/RSI overlays and signal markers are daily-only,
 * the price prediction shows on every timeframe. */
export function StockChartPanel({
  exchange,
  symbol,
  levels,
}: {
  exchange: Exchange;
  symbol: string;
  /** Strategy levels to draw on the daily chart. */
  levels?: PriceLevel[];
}) {
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
  // Optional overlay, off until switched on: a failed or empty forecast never blocks the chart.
  const [predicting, setPredicting] = useState(false);
  const forecast = useAsync(predicting ? `forecast:${stock}` : null, (signal) =>
    getForecast(exchange, symbol, signal),
  );
  const [picked, setPicked] = useState<string | null>(null);
  const best = forecast.data?.best_model ?? null;
  const forecasts = useMemo(() => forecast.data?.forecasts ?? [], [forecast.data]);
  const comparing = picked === COMPARE;
  const model = forecasts.find((f) => f.model === picked) ?? forecasts.find((f) => f.model === best) ?? forecasts[0];
  const shownForecasts = useMemo(
    () => (!predicting ? [] : comparing ? forecasts : model ? [model] : []),
    [predicting, comparing, forecasts, model],
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
      forecasts: shownForecasts.map((f) => toLine(f, timeframe)),
    };
  }, [bars.data, indicators.data, volumeSignals.data, swing.data, daily, initialBars, shownForecasts, timeframe]);

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
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm font-medium">
            <Switch checked={predicting} onChange={setPredicting} label="Show price prediction" />
            Prediction
          </label>
          <SegmentedControl
            label="Prediction model"
            options={MODEL_OPTIONS}
            value={comparing ? COMPARE : (model?.model ?? picked ?? best ?? "holt")}
            onChange={(value) => {
              setPicked(value);
              setPredicting(true); // choosing a model means "show me it"
            }}
          />
          <SegmentedControl label="Timeframe" options={RANGE_OPTIONS} value={range} onChange={setRange} />
        </div>
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
        <PriceChart data={chartData} levels={daily ? levels : undefined} />
      )}

      {overlayIssues.length > 0 && !loading ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Couldn&apos;t load {overlayIssues.join(", ")}; showing the chart without them.
        </p>
      ) : null}
      {predicting && forecast.error ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">Couldn&apos;t load the price prediction.</p>
      ) : null}
      {predicting && forecast.data && !model ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">No prediction yet: this stock needs a year of history.</p>
      ) : null}
      {shownForecasts.length > 0 && chartData ? (
        <div className="space-y-2">
          <PredictionLegend
            forecasts={shownForecasts}
            bars={chartData.bars}
            timeframe={timeframe}
            best={best}
            onPick={comparing ? setPicked : undefined}
          />
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            The line is what each model would have predicted at the time, from forecasts made every{" "}
            {shownForecasts[0].horizon} sessions using only earlier prices. Deviation is
            how far the actual close is from the prediction (+ = above).
            {daily ? "" : " Weekly and monthly views use each period\u2019s last-session prediction."} Statistical projection from past prices,
            not advice.
          </p>
        </div>
      ) : null}
      {daily ? null : (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          EMA, RSI and signal markers are shown on the 1D chart.
        </p>
      )}
    </section>
  );
}
