"use client";

import { formatSigned, tradingDate } from "@/lib/format";
import type { Bar, ModelForecast, Timeframe } from "@/lib/types";
import { CHART_COLORS } from "./chart-theme";
import type { ForecastLine } from "./price-chart";

export const COMPARE = "compare";

const MODEL_META: Record<string, { name: string; color: string }> = {
  drift: { name: "Drift", color: CHART_COLORS.forecastDrift },
  holt: { name: "Holt", color: CHART_COLORS.forecastHolt },
  ridge: { name: "Ridge", color: CHART_COLORS.forecastRidge },
};
const meta = (model: string) => MODEL_META[model] ?? { name: model, color: CHART_COLORS.forecastHolt };

export const modelName = (model: string) => meta(model).name;

/** Selector options, fixed so the selector shows before any forecast has loaded. */
export const MODEL_OPTIONS = [
  ...Object.entries(MODEL_META).map(([value, m]) => ({ value, label: m.name })),
  { value: COMPARE, label: "Compare" },
];

type DailyPoint = { date: string; close: number };

/** The bar a trading date belongs to: weekly bars are stamped with their Monday, monthly with the 1st. */
function bucket(date: string, timeframe: Timeframe): string {
  if (timeframe === "1mo") return `${date.slice(0, 7)}-01`;
  if (timeframe !== "1w") return date;
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

/** Daily forecast points as the chart's bars: each period's prediction is the one for its last
 * session, the same way a weekly or monthly candle's close is its last day's close. */
function resample(points: DailyPoint[], timeframe: Timeframe): DailyPoint[] {
  const byBar = new Map<string, number>();
  for (const p of points) byBar.set(bucket(p.date, timeframe), p.close); // ascending: last wins
  return [...byBar].map(([date, close]) => ({ date, close }));
}

export function toLine(f: ModelForecast, timeframe: Timeframe): ForecastLine {
  const line = (points: DailyPoint[]) => resample(points, timeframe).map((p) => ({ time: p.date, value: p.close }));
  return { color: meta(f.model).color, history: line(f.history) };
}

export interface Deviation {
  /** Latest close vs the model's prediction for that session, in % (+ = price above it). */
  now: number | null;
  /** Mean absolute deviation over the sessions on the chart that have a prediction, in %. */
  average: number | null;
}

/** How far the actual closes strayed from what the model predicted for those sessions. */
export function deviation(f: ModelForecast, bars: Bar[], timeframe: Timeframe): Deviation {
  const predicted = new Map(resample(f.history, timeframe).map((p) => [p.date, p.close]));
  const gaps: number[] = [];
  for (const bar of bars) {
    const p = predicted.get(tradingDate(bar.ts));
    if (p) gaps.push((bar.close / p - 1) * 100);
  }
  const last = bars.at(-1);
  const p = last ? predicted.get(tradingDate(last.ts)) : undefined;
  return {
    now: last && p ? (last.close / p - 1) * 100 : null,
    average: gaps.length ? gaps.reduce((sum, g) => sum + Math.abs(g), 0) / gaps.length : null,
  };
}

const tone = (v: number) => (v >= 0 ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500");

/** One row per shown model: its colour, past accuracy and how far price is from it right now.
 * In compare mode each row has a "Use" button to pick that model. */
export function PredictionLegend({
  forecasts,
  bars,
  timeframe,
  best,
  onPick,
}: {
  forecasts: ModelForecast[];
  bars: Bar[];
  timeframe: Timeframe;
  best: string | null;
  onPick?: (model: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[520px] text-xs">
        <thead className="bg-zinc-50 text-left uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-1.5 font-medium">Model</th>
            <th className="px-3 py-1.5 text-right font-medium" title="Price now vs the model's prediction for today">
              Deviation now
            </th>
            <th className="px-3 py-1.5 text-right font-medium" title="Average gap between price and prediction on this chart">
              Avg deviation
            </th>
            <th className="px-3 py-1.5 text-right font-medium" title="Share of 30-session forecasts that got the direction right">
              Direction right
            </th>
            {onPick ? <th className="px-3 py-1.5" /> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {forecasts.map((f) => {
            const dev = deviation(f, bars, timeframe);
            const { name, color } = meta(f.model);
            return (
              <tr key={f.model}>
                <td className="px-3 py-1.5">
                  <span className="inline-flex items-center gap-2 font-medium">
                    <span aria-hidden className="inline-block h-1 w-5 rounded-full" style={{ backgroundColor: color }} />
                    {name}
                    {f.model === best ? (
                      <span className="rounded bg-zinc-100 px-1 py-px text-[10px] font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                        BEST
                      </span>
                    ) : null}
                  </span>
                </td>
                <td className={`px-3 py-1.5 text-right font-semibold tabular-nums ${dev.now == null ? "" : tone(dev.now)}`}>
                  {dev.now == null ? "—" : `${formatSigned(dev.now, 1)}%`}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {dev.average == null ? "—" : `${dev.average.toFixed(1)}%`}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {f.metrics.hit_rate == null ? "—" : `${Math.round(f.metrics.hit_rate * 100)}%`}
                </td>
                {onPick ? (
                  <td className="px-3 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => onPick(f.model)}
                      className="rounded-md border border-zinc-300 px-2 py-0.5 font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    >
                      Use
                    </button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
