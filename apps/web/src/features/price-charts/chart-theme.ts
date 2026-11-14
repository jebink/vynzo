import { ColorType, type DeepPartial, type ChartOptions } from "lightweight-charts";

// Palette shared by the chart, its legend and the marker key (Tailwind colour values).
export const CHART_COLORS = {
  up: "#16a34a", // green-600
  down: "#dc2626", // red-600
  volumeUp: "rgba(22, 163, 74, 0.35)",
  volumeDown: "rgba(220, 38, 38, 0.35)",
  ema21: "#f59e0b", // amber-500
  ema50: "#3b82f6", // blue-500
  ema200: "#a855f7", // purple-500
  rsi: "#0ea5e9", // sky-500
  rsiGuide: "#a1a1aa", // zinc-400
  highVolumeBuy: "#06b6d4", // cyan-500
  swingBuy: "#16a34a",
  swingSell: "#dc2626",
} as const;

/** Layout, grid and scale colours that follow the app's zinc light/dark palette. */
export function chartThemeOptions(isDark: boolean): DeepPartial<ChartOptions> {
  const text = isDark ? "#a1a1aa" : "#52525b"; // zinc-400 / zinc-600
  const grid = isDark ? "#1c1c1f" : "#f4f4f5"; // ~zinc-900 / zinc-100
  const border = isDark ? "#27272a" : "#e4e4e7"; // zinc-800 / zinc-200
  return {
    layout: {
      background: { type: ColorType.Solid, color: isDark ? "#0a0a0a" : "#ffffff" },
      textColor: text,
      panes: { separatorColor: border, separatorHoverColor: isDark ? "#3f3f46" : "#d4d4d8" },
    },
    grid: {
      vertLines: { color: grid },
      horzLines: { color: grid },
    },
    rightPriceScale: { borderColor: border },
    timeScale: { borderColor: border },
    crosshair: {
      vertLine: { labelBackgroundColor: isDark ? "#3f3f46" : "#52525b" },
      horzLine: { labelBackgroundColor: isDark ? "#3f3f46" : "#52525b" },
    },
  };
}
