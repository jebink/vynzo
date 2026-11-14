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
