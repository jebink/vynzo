// Which strategy tags a stock shows per horizon, and the chart levels for a selected one.
import { FACTOR_CONFLUENCE, STRATEGIES, setupLabel } from "@/features/opportunities/horizons";
import type { Direction, Horizon, StockPick, StockSetup, StockStrategiesResponse } from "@/lib/types";

export interface StrategyTag {
  /** Matches the backtest's strategy ids: "<horizon>:<key>". */
  id: string;
  horizon: Horizon;
  key: string;
  label: string;
  description: string;
  direction: Direction;
  /** The named setup behind the tag; absent for Factor confluence. */
  setup?: StockSetup;
}

/** Swing: every setup detected today (either direction), plus Factor confluence when the
 * engine picked the stock without a named setup. Other horizons: Factor confluence if picked. */
export function tagsFor(data: StockStrategiesResponse, horizon: Horizon): StrategyTag[] {
  const pick = data.horizons[horizon]?.pick ?? null;
  const tags: StrategyTag[] = [];
  if (horizon === "swing") {
    for (const setup of data.setups) {
      tags.push({
        id: `swing:${setup.key}`,
        horizon,
        key: setup.key,
        label: setupLabel(setup.key, setup.variant),
        description: STRATEGIES.find((s) => s.key === setup.key)?.description ?? "",
        direction: setup.direction,
        setup,
      });
    }
  }
  if (pick && (horizon !== "swing" || pick.setups.length === 0)) {
    tags.push({
      id: `${horizon}:${FACTOR_CONFLUENCE.key}`,
      horizon,
      key: FACTOR_CONFLUENCE.key,
      label: FACTOR_CONFLUENCE.name,
      description: FACTOR_CONFLUENCE.description,
      direction: pick.direction,
    });
  }
  return tags;
}

/** Line colours per level kind on the price chart. */
export const LEVEL_COLORS: Record<ChartLevel["kind"], string> = {
  entry: "#0ea5e9",
  stop: "#dc2626",
  target: "#16a34a",
  support: "#a1a1aa",
  resistance: "#a1a1aa",
};

export interface ChartLevel {
  price: number;
  label: string;
  kind: "entry" | "stop" | "target" | "support" | "resistance";
}

/** Levels to draw on the price chart for a selected tag. A setup borrows the horizon's plan
 * when the engine's pick points the same way; otherwise it shows the setup's own stop. */
export function levelsFor(tag: StrategyTag, pick: StockPick | null): ChartLevel[] {
  const plan = pick && pick.direction === tag.direction ? pick : null;
  const out: ChartLevel[] = [];
  if (plan) {
    out.push({ price: plan.entry_low, label: "Entry low", kind: "entry" });
    out.push({ price: plan.entry_high, label: "Entry high", kind: "entry" });
    plan.targets.forEach((t, i) => out.push({ price: t, label: `Target ${i + 1}`, kind: "target" }));
    if (plan.supports[0] != null) out.push({ price: plan.supports[0], label: "Support", kind: "support" });
    if (plan.resistances[0] != null) {
      out.push({ price: plan.resistances[0], label: "Resistance", kind: "resistance" });
    }
  }
  out.push({ price: tag.setup?.stop ?? plan?.stop_loss ?? NaN, label: "Stop", kind: "stop" });
  return out.filter((l) => Number.isFinite(l.price));
}
