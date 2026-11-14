import type { Horizon } from "@/lib/types";

/** Display copy per trading horizon. Order is the tab order. */
export const HORIZONS: readonly { id: Horizon; label: string; summary: string; notes: string[] }[] = [
  {
    id: "next_session",
    label: "Intraday",
    summary: "Setups for the next trading session, from today's close. Exit by the close.",
    notes: [
      "Computed from end-of-day prices, not live data: confirm the trigger price in the session before entering.",
    ],
  },
  {
    id: "swing",
    label: "Swing",
    summary: "Trades held for a few days to several weeks.",
    notes: [
      "SELL means exit or avoid, and is monitor-only: SELL setups lost money in the backtest. Holding a short position overnight needs futures or options.",
    ],
  },
  {
    id: "long_term",
    label: "Long-term",
    summary: "Positions held for several months to a year.",
    notes: [
      "Fundamentals (results, valuation, debt) are not included yet: this is trend and relative strength only, so confidence is capped at medium.",
      "SELL means exit or avoid, and is monitor-only: SELL setups lost money in the backtest.",
    ],
  },
];

export const FACTOR_LABELS: Record<string, string> = {
  trend: "Trend",
  momentum: "Momentum",
  price_action: "Price action",
  volume: "Volume",
  volatility: "Volatility",
  relative_strength: "Relative strength",
};

/** The ten swing strategies the engine detects (analytics-worker opportunities/strategies.py). */
export const STRATEGIES: readonly { key: string; name: string; description: string }[] = [
  { key: "trend_pullback", name: "Trend pullback", description: "In an uptrend, the price dipped to the rising 21-day EMA and bounced." },
  { key: "breakout", name: "Breakout", description: "Closed above the 20-day high on at least 1.5× normal volume." },
  { key: "ma_crossover", name: "MA crossover", description: "The 9-day EMA crossed the 21-day EMA, or the 50-day crossed the 200-day." },
  { key: "rsi_pullback", name: "RSI pullback", description: "In an uptrend, RSI(14) dipped to 38–50 and turned back up." },
  { key: "macd_momentum", name: "MACD momentum", description: "The MACD line crossed its signal line within the last two sessions." },
  { key: "squeeze_breakout", name: "Squeeze breakout", description: "Bollinger bands left a 120-day narrow and the price broke out of the quiet range." },
  { key: "support_bounce", name: "Support bounce", description: "The price tested a support level and closed strongly off it." },
  { key: "relative_strength", name: "RS leader", description: "Beat NIFTY by 10+ points over 63 sessions and is still leading over 20." },
  { key: "volume_accumulation", name: "Volume / accumulation", description: "An up day on 2× normal volume, or OBV rising while the price held steady." },
  { key: "chart_pattern", name: "Chart pattern", description: "Broke out of a flag, cup and handle, double bottom or ascending triangle." },
];

const PATTERN_LABELS: Record<string, string> = {
  flag: "Flag",
  cup_and_handle: "Cup and handle",
  double_bottom: "Double bottom",
  ascending_triangle: "Ascending triangle",
};

/** Display name for a setup, naming the chart pattern or crossover when there is one. */
export function setupLabel(key: string, variant: string): string {
  if (key === "chart_pattern" && PATTERN_LABELS[variant]) return PATTERN_LABELS[variant];
  const name = STRATEGIES.find((s) => s.key === key)?.name ?? key;
  return key === "ma_crossover" && variant ? `${variant} EMA cross` : name;
}
