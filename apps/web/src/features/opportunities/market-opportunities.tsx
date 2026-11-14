"use client";

import { useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate } from "@/lib/format";
import { getOpportunities } from "@/lib/market-api";
import type { Confidence, Direction, Horizon, MarketRegime, Opportunity } from "@/lib/types";
import { HORIZONS, STRATEGIES } from "./horizons";
import { OpportunityCard } from "./opportunity-card";
import { PerformancePanel } from "./performance-panel";

// The original engine: picks from the six-factor score alone, with no named setup attached.
const FACTOR_CONFLUENCE = {
  key: "factor_confluence",
  name: "Factor confluence",
  description: "At least three of six factor groups (trend, momentum, price action, volume, volatility, relative strength) agree, with no named setup.",
};

function matchesStrategy(pick: Opportunity, key: string): boolean {
  return key === FACTOR_CONFLUENCE.key ? pick.setups.length === 0 : pick.setups.some((s) => s.key === key);
}

type DirectionFilter = "ALL" | Direction;
type ConfidenceFilter = "any" | "medium" | "high";
type View = "picks" | "performance";

const DIRECTION_OPTIONS = [
  { value: "ALL", label: "All" },
  { value: "BUY", label: "Buy" },
  { value: "SELL", label: "Sell" },
] as const;

const CONFIDENCE_OPTIONS = [
  { value: "any", label: "Any" },
  { value: "medium", label: "Medium+" },
  { value: "high", label: "High" },
] as const;

const VIEW_OPTIONS = [
  { value: "picks", label: "Opportunities" },
  { value: "performance", label: "Track record" },
] as const;

const CONFIDENCE_RANK: Record<Confidence, number> = { low: 0, medium: 1, high: 2 };

const REGIME_STYLE: Record<MarketRegime["label"], string> = {
  bullish: "border-green-300 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300",
  bearish: "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300",
  neutral: "border-zinc-300 bg-zinc-50 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
  unknown: "border-zinc-300 bg-zinc-50 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
};

/** The Market screen: ranked BUY/SELL opportunities for three horizons, with a track record. */
export function MarketOpportunities() {
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [direction, setDirection] = useState<DirectionFilter>("ALL");
  const [confidence, setConfidence] = useState<ConfidenceFilter>("any");
  const [strategy, setStrategy] = useState<string>("any");
  const [view, setView] = useState<View>("picks");
  const data = useAsync("opportunities", (signal) => getOpportunities(signal));

  const info = HORIZONS.find((h) => h.id === horizon) ?? HORIZONS[0];
  const all = data.data?.horizons[horizon] ?? [];
  const minConfidence = confidence === "any" ? 0 : CONFIDENCE_RANK[confidence];
  const strategyFilter = horizon === "swing" ? strategy : "any";
  const shown = all.filter(
    (pick) =>
      (direction === "ALL" || pick.direction === direction) &&
      CONFIDENCE_RANK[pick.confidence] >= minConfidence &&
      (strategyFilter === "any" || matchesStrategy(pick, strategyFilter)),
  );
  const actionable = shown.filter((pick) => pick.status === "actionable");
  const watch = shown.filter((pick) => pick.status === "watch");
  const emptyReason =
    horizon === "next_session"
      ? "Intraday setups are monitor-only until a live intraday data feed is added: without it the entry trigger can't be confirmed, and setups computed from daily bars showed no reliable edge."
      : all.some((pick) => pick.status === "actionable")
        ? "No actionable pick matches these filters."
        : all.length
          ? "No stock passed every check at the last close. The closest candidates are listed under Worth monitoring."
          : "Nothing in this horizon met the selection criteria at the last close.";

  return (
    <div className="space-y-5">
      {data.data ? <DataStrip asOf={data.data.as_of} regime={data.data.regime} note={data.data.data_note} /> : null}

      <div role="tablist" aria-label="Trading horizon" className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-zinc-200 dark:border-zinc-800">
        {HORIZONS.map((h) => {
          const picks = data.data?.horizons[h.id] ?? [];
          const count = picks.filter((p) => p.status === "actionable").length;
          const selected = h.id === horizon;
          return (
            <button
              key={h.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setHorizon(h.id)}
              className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium ${
                selected
                  ? "border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-50"
                  : "border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              {h.label}
              {data.data ? (
                <span className="ml-1.5 rounded-full bg-zinc-100 px-1.5 text-xs tabular-nums text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="space-y-1">
        <p className="text-sm text-zinc-700 dark:text-zinc-300">{info.summary}</p>
        {info.notes.map((note) => (
          <p key={note} className="text-xs text-zinc-500 dark:text-zinc-400">
            {note}
          </p>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl label="View" options={VIEW_OPTIONS} value={view} onChange={setView} />
        {view === "picks" ? (
          <>
            <SegmentedControl label="Direction" options={DIRECTION_OPTIONS} value={direction} onChange={setDirection} />
            <SegmentedControl label="Confidence" options={CONFIDENCE_OPTIONS} value={confidence} onChange={setConfidence} />
            {horizon === "swing" ? <StrategySelect picks={all} value={strategy} onChange={setStrategy} /> : null}
          </>
        ) : null}
      </div>

      {view === "performance" ? (
        <PerformancePanel horizon={horizon} />
      ) : data.error ? (
        <ErrorState title="Couldn't load opportunities" error={data.error} />
      ) : !data.data ? (
        <LoadingState label="Loading opportunities…" />
      ) : (
        <div className="space-y-8">
          <PickSection
            title="Actionable"
            description="Passed every check: multi-factor confluence, risk/reward, liquidity and confidence. Ranked by score."
            picks={actionable}
            empty={
              <EmptyState
                title="No High-Conviction Opportunities Currently Available"
                description={emptyReason}
              />
            }
          />
          {watch.length ? (
            <PickSection
              title="Worth monitoring"
              description="Promising but not actionable yet: a lower score, weaker confidence, a stretched entry or a nearby level limiting the move."
              picks={watch}
            />
          ) : null}
        </div>
      )}

      <p className="border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        For research only, not investment advice. Picks are generated by a rules-based model from
        end-of-day prices and can be wrong; check the chart, news and results before trading. Sector,
        fundamentals, FII/DII flows and news are not part of the model yet.
      </p>
    </div>
  );
}

/** Filter swing picks by named strategy; each option shows how many of today's picks have it. */
function StrategySelect({
  picks,
  value,
  onChange,
}: {
  picks: Opportunity[];
  value: string;
  onChange: (value: string) => void;
}) {
  const count = (key: string) => picks.filter((p) => matchesStrategy(p, key)).length;
  const description = [FACTOR_CONFLUENCE, ...STRATEGIES].find((s) => s.key === value)?.description;
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-zinc-600 dark:text-zinc-400">Strategy</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        title={description}
        className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
      >
        <option value="any">Any</option>
        {[FACTOR_CONFLUENCE, ...STRATEGIES].map((s) => (
          <option key={s.key} value={s.key}>
            {s.name} ({count(s.key)})
          </option>
        ))}
      </select>
    </label>
  );
}

function PickSection({
  title,
  description,
  picks,
  empty,
}: {
  title: string;
  description: string;
  picks: Opportunity[];
  empty?: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">
          {title} <span className="text-sm font-normal text-zinc-500 tabular-nums dark:text-zinc-400">{picks.length}</span>
        </h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{description}</p>
      </div>
      {picks.length === 0 ? (
        empty
      ) : (
        <div className="space-y-3">
          {picks.map((pick) => (
            <OpportunityCard key={pick.id} pick={pick} />
          ))}
        </div>
      )}
    </section>
  );
}

function DataStrip({ asOf, regime, note }: { asOf: string | null; regime: MarketRegime | null; note: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
      <span className="text-zinc-600 dark:text-zinc-400">
        {asOf ? (
          <>
            Based on the close of <span className="font-medium text-zinc-900 dark:text-zinc-100">{formatDate(asOf)}</span>
          </>
        ) : (
          "No picks have been generated yet"
        )}
      </span>
      {regime ? (
        <span
          title={regime.notes.join("\n")}
          className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${REGIME_STYLE[regime.label]}`}
        >
          Market {regime.label}
        </span>
      ) : null}
      <span className="basis-full text-xs text-zinc-500 dark:text-zinc-400">
        {note}
        {regime?.notes.length ? ` ${regime.notes.join(". ")}.` : ""}
      </span>
    </div>
  );
}
