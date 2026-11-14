"use client";

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarkerBar,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { usePrefersDark } from "@/hooks/use-prefers-dark";
import { formatDate, formatNumber, formatSigned, formatVolume, tradingDate } from "@/lib/format";
import type { Bar, IndicatorRow } from "@/lib/types";
import { CHART_COLORS, chartThemeOptions } from "./chart-theme";

export type ChartMarkerKind = "HIGH_VOLUME_BUY" | "SWING_BUY" | "SWING_SELL";

export interface ChartMarker {
  /** Trading date, "YYYY-MM-DD". */
  time: string;
  kind: ChartMarkerKind;
}

/** A horizontal price line, e.g. a strategy's entry, stop or target. */
export interface PriceLevel {
  price: number;
  label: string;
  color: string;
}

export interface PriceChartData {
  bars: Bar[];
  /** Daily indicators (EMA overlays and the RSI pane); null hides them. */
  indicators: IndicatorRow[] | null;
  /** Signal markers; null when markers don't apply (non-daily timeframes). */
  markers: ChartMarker[] | null;
  /** How many of the newest bars to show initially (the rest is a scroll away). */
  initialBars: number;
  /** Prediction lines; empty or null hides them. */
  forecasts?: ForecastLine[] | null;
}

type Point = { time: string; value: number };

/** One model's line: what it would have predicted for past sessions, then its projection. */
export interface ForecastLine {
  color: string;
  history: Point[];
  future: Point[];
}

const MARKER_STYLE: Record<ChartMarkerKind, Omit<SeriesMarkerBar<Time>, "time">> = {
  HIGH_VOLUME_BUY: { position: "belowBar", shape: "arrowUp", color: CHART_COLORS.highVolumeBuy, text: "HV" },
  SWING_BUY: { position: "belowBar", shape: "arrowUp", color: CHART_COLORS.swingBuy, text: "BUY" },
  SWING_SELL: { position: "aboveBar", shape: "arrowDown", color: CHART_COLORS.swingSell, text: "SELL" },
};

const EMAS = [
  { key: "ema_21", label: "EMA 21", color: CHART_COLORS.ema21 },
  { key: "ema_50", label: "EMA 50", color: CHART_COLORS.ema50 },
  { key: "ema_200", label: "EMA 200", color: CHART_COLORS.ema200 },
] as const;

function lineData(rows: IndicatorRow[], pick: (row: IndicatorRow) => number | null): LineData<Time>[] {
  const out: LineData<Time>[] = [];
  for (const row of rows) {
    const value = pick(row);
    if (value != null) out.push({ time: tradingDate(row.ts), value });
  }
  return out;
}

/**
 * Candlestick chart with a volume histogram, optional EMA overlays, signal markers and an RSI(14)
 * pane. The chart is created in an effect (lightweight-charts needs `window`) and removed on unmount.
 */
export function PriceChart({ data, levels = [] }: { data: PriceChartData; levels?: PriceLevel[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const isDarkRef = useRef(false);
  const isDark = usePrefersDark();
  // Index into data.bars of the bar under the crosshair; null = the newest bar.
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const hasIndicators = data.indicators !== null && data.indicators.length > 0;

  // Theme: remember it for chart creation and restyle a live chart in place.
  useEffect(() => {
    isDarkRef.current = isDark;
    chartRef.current?.applyOptions(chartThemeOptions(isDark));
  }, [isDark]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const theme = chartThemeOptions(isDarkRef.current);
    const chart = createChart(container, {
      autoSize: true,
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.25 } },
      timeScale: { rightOffset: 4, minBarSpacing: 1 },
      ...theme,
      layout: { ...theme.layout, attributionLogo: false },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: CHART_COLORS.up,
      downColor: CHART_COLORS.down,
      borderVisible: false,
      wickUpColor: CHART_COLORS.up,
      wickDownColor: CHART_COLORS.down,
    });
    candlesRef.current = candles;
    candles.setData(
      data.bars.map((bar) => ({
        time: tradingDate(bar.ts),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );

    // Volume on its own overlay scale, squeezed into the bottom fifth of the price pane.
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volume.setData(
      data.bars.map((bar) => ({
        time: tradingDate(bar.ts),
        value: bar.volume,
        color: bar.close >= bar.open ? CHART_COLORS.volumeUp : CHART_COLORS.volumeDown,
      })),
    );

    if (data.indicators && data.indicators.length > 0) {
      const rows = data.indicators;
      for (const ema of EMAS) {
        const line = chart.addSeries(LineSeries, {
          color: ema.color,
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData(lineData(rows, (row) => row[ema.key]));
      }

      const rsi = chart.addSeries(
        LineSeries,
        {
          color: CHART_COLORS.rsi,
          lineWidth: 1,
          priceLineVisible: false,
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
        },
        1,
      );
      rsi.setData(lineData(rows, (row) => row.rsi_14));
      for (const level of [70, 30]) {
        rsi.createPriceLine({
          price: level,
          color: CHART_COLORS.rsiGuide,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "",
        });
      }
      const [pricePane, rsiPane] = chart.panes();
      pricePane?.setStretchFactor(3);
      rsiPane?.setStretchFactor(1);
    }

    const forecasts = data.forecasts ?? [];
    const lastTime = data.bars.length ? tradingDate(data.bars[data.bars.length - 1].ts) : "";
    let ahead = 0;
    for (const f of forecasts) {
      const style = { color: f.color, priceLineVisible: false, crosshairMarkerVisible: false };
      if (f.history.length > 0) chart.addSeries(LineSeries, { ...style, lineWidth: 2, lastValueVisible: false }).setData(f.history);
      // A period still in progress already has its candle: the projection starts after it.
      const future = f.future.filter((p) => p.time > lastTime);
      ahead = Math.max(ahead, future.length);
      if (future.length > 0) {
        const last = data.bars[data.bars.length - 1];
        chart
          .addSeries(LineSeries, { ...style, lineWidth: 2, lastValueVisible: true })
          .setData([{ time: lastTime, value: last.close }, ...future]);
      }
    }

    const barTimes = new Set(data.bars.map((bar) => tradingDate(bar.ts)));
    const markers = (data.markers ?? [])
      .filter((marker) => barTimes.has(marker.time))
      .sort((a, b) => a.time.localeCompare(b.time))
      .map((marker): SeriesMarkerBar<Time> => ({ time: marker.time, ...MARKER_STYLE[marker.kind] }));
    if (markers.length > 0) createSeriesMarkers(candles, markers);

    const count = data.bars.length;
    if (count > data.initialBars) {
      chart.timeScale().setVisibleLogicalRange({ from: count - data.initialBars, to: count + ahead + 3 });
    } else {
      chart.timeScale().fitContent();
    }

    chart.subscribeCrosshairMove((param) => {
      const index = param.logical;
      setHoverIndex(index !== undefined && index >= 0 && index < count ? Math.round(index) : null);
    });

    return () => {
      chartRef.current = null;
      candlesRef.current = null;
      chart.remove();
    };
  }, [data]);

  // Strategy levels as price lines on the live chart; runs after the chart effect above.
  useEffect(() => {
    const candles = candlesRef.current;
    if (!candles) return;
    const lines = levels.map((level) =>
      candles.createPriceLine({
        price: level.price,
        color: level.color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.label,
      }),
    );
    return () => {
      for (const line of lines) candles.removePriceLine(line);
    };
  }, [levels, data]);

  const index = hoverIndex ?? data.bars.length - 1;
  const bar = data.bars[index];
  const prevClose = index > 0 ? data.bars[index - 1]?.close : undefined;
  const row = bar && hasIndicators ? data.indicators?.find((r) => r.ts === bar.ts) : undefined;

  return (
    <div className="space-y-2">
      <div className="relative">
        <div
          ref={containerRef}
          className={`w-full ${hasIndicators ? "h-[560px]" : "h-[440px]"}`}
          aria-label="Candlestick price chart"
          role="img"
        />
        {bar ? (
          <div className="pointer-events-none absolute left-2 top-1 z-10 flex flex-wrap gap-x-3 gap-y-0.5 rounded bg-white/80 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 tabular-nums dark:bg-zinc-950/70 dark:text-zinc-400">
            <span className="text-zinc-900 dark:text-zinc-100">{formatDate(bar.ts)}</span>
            <span>O {formatNumber(bar.open)}</span>
            <span>H {formatNumber(bar.high)}</span>
            <span>L {formatNumber(bar.low)}</span>
            <span>C {formatNumber(bar.close)}</span>
            {prevClose ? (
              <span className={bar.close >= prevClose ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500"}>
                {formatSigned(((bar.close - prevClose) / prevClose) * 100)}%
              </span>
            ) : null}
            <span>Vol {formatVolume(bar.volume)}</span>
            {row
              ? EMAS.map((ema) => (
                  <span key={ema.key} style={{ color: ema.color }}>
                    {ema.label} {formatNumber(row[ema.key])}
                  </span>
                ))
              : null}
            {row ? <span style={{ color: CHART_COLORS.rsi }}>RSI 14 {formatNumber(row.rsi_14, 1)}</span> : null}
          </div>
        ) : null}
      </div>
      <ChartLegend showIndicators={hasIndicators} showMarkers={data.markers !== null} />
    </div>
  );
}

function Swatch({ color, label, shape = "line" }: { color: string; label: string; shape?: "line" | "up" | "down" | "bar" }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {shape === "line" ? (
        <span className="inline-block h-0.5 w-4 rounded" style={{ backgroundColor: color }} />
      ) : shape === "bar" ? (
        <span className="inline-block h-2.5 w-2 rounded-sm" style={{ backgroundColor: color }} />
      ) : (
        <span aria-hidden style={{ color }}>
          {shape === "up" ? "▲" : "▼"}
        </span>
      )}
      {label}
    </span>
  );
}

function ChartLegend({ showIndicators, showMarkers }: { showIndicators: boolean; showMarkers: boolean }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
      <Swatch color={CHART_COLORS.volumeUp} label="Volume" shape="bar" />
      {showIndicators ? (
        <>
          {EMAS.map((ema) => (
            <Swatch key={ema.key} color={ema.color} label={ema.label} />
          ))}
          <Swatch color={CHART_COLORS.rsi} label="RSI 14 (30/70)" />
        </>
      ) : null}
      {showMarkers ? (
        <>
          <Swatch color={CHART_COLORS.highVolumeBuy} label="High volume buy" shape="up" />
          <Swatch color={CHART_COLORS.swingBuy} label="Swing buy" shape="up" />
          <Swatch color={CHART_COLORS.swingSell} label="Swing sell" shape="down" />
        </>
      ) : null}
    </div>
  );
}
