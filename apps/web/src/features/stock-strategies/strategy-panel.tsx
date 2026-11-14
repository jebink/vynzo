"use client";

import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/status";
import { FactorRow } from "@/features/opportunities/opportunity-card";
import { HORIZONS } from "@/features/opportunities/horizons";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatPrice } from "@/lib/format";
import { getStockStrategies } from "@/lib/market-api";
import type { Exchange, Horizon, StockPick, StockStrategiesResponse } from "@/lib/types";
import { BacktestReplay, useBacktest } from "./backtest";
import { type ChartLevel, type StrategyTag, levelsFor, tagsFor } from "./model";

const DIRECTION_TONE = {
  BUY: "text-green-700 dark:text-green-400",
  SELL: "text-red-700 dark:text-red-400",
};

/** The stock page's first panel: which strategies the stock falls under per horizon, why, and a
 * full-history backtest of the selected one. Reports chart levels for the selection. Key it by
 * stock so navigating to another stock starts fresh. */
export function StrategyPanel({
  exchange,
  symbol,
  onLevels,
}: {
  exchange: Exchange;
  symbol: string;
  onLevels: (levels: ChartLevel[]) => void;
}) {
  const data = useAsync(`stock-strategies:${exchange}:${symbol}`, (signal) =>
    getStockStrategies(exchange, symbol, signal),
  );
  const [selected, setSelected] = useState<StrategyTag | null>(null);
  const { run, start } = useBacktest(exchange, symbol);
  const [animateFor, setAnimateFor] = useState<string | null>(null);
  const [replays, setReplays] = useState(0);

  useEffect(() => {
    const pick = selected && data.data ? data.data.horizons[selected.horizon]?.pick ?? null : null;
    onLevels(selected ? levelsFor(selected, pick) : []);
  }, [selected, data.data, onLevels]);

  const select = (tag: StrategyTag) => {
    setSelected((prev) => (prev?.id === tag.id ? null : tag));
    setAnimateFor(null);
  };
  const backtest = (tag: StrategyTag) => {
    setAnimateFor(tag.id);
    setReplays((n) => n + 1);
    start();
  };

  return (
    <section aria-labelledby="strategies-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="strategies-heading" className="text-lg font-semibold">
          Strategies
        </h2>
        {data.data?.as_of ? (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            As of the {formatDate(data.data.as_of)} close
            {data.data.regime ? ` · market ${data.data.regime.label}` : ""} · select a strategy to see why
          </p>
        ) : null}
      </div>

      {data.error ? (
        <ErrorState title="Couldn't load strategies" error={data.error} />
      ) : !data.data ? (
        <LoadingState label="Scoring this stock…" />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {HORIZONS.map((h) => (
              <HorizonColumn
                key={h.id}
                horizon={h.id}
                label={h.label}
                data={data.data!}
                selected={selected?.id ?? null}
                onSelect={select}
              />
            ))}
          </div>
          {selected ? (
            <StrategyDetail
              tag={selected}
              pick={data.data.horizons[selected.horizon]?.pick ?? null}
              onBacktest={() => backtest(selected)}
              backtestBusy={run.status === "running"}
            />
          ) : null}
          {selected && run.status !== "idle" ? (
            run.status === "error" ? (
              <ErrorState title="Backtest failed" error={new Error(run.error ?? "unknown error")} />
            ) : (
              <BacktestReplay
                key={`${selected.id}:${replays}`}
                run={run}
                strategy={selected.id}
                label={selected.label}
                animate={animateFor === selected.id}
                onReplay={() => backtest(selected)}
              />
            )
          ) : null}
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            For research only, not investment advice. Rules-based, from end-of-day prices.
          </p>
        </>
      )}
    </section>
  );
}

function HorizonColumn({
  horizon,
  label,
  data,
  selected,
  onSelect,
}: {
  horizon: Horizon;
  label: string;
  data: StockStrategiesResponse;
  selected: string | null;
  onSelect: (tag: StrategyTag) => void;
}) {
  const { pick, rejection } = data.horizons[horizon] ?? { pick: null, rejection: null };
  const tags = tagsFor(data, horizon);
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        {pick ? (
          <span className="text-xs tabular-nums">
            <span className={`font-semibold ${DIRECTION_TONE[pick.direction]}`}>{pick.direction}</span>
            {" · "}
            {pick.status === "actionable" ? "Actionable" : "Monitor"} · {pick.score}
          </span>
        ) : (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">No pick</span>
        )}
      </div>
      {tags.length ? (
        <ul aria-label={`${label} strategies`} className="mt-2 flex flex-wrap gap-1.5">
          {tags.map((tag) => {
            const active = tag.id === selected;
            return (
              <li key={`${tag.id}:${tag.direction}`}>
                <button
                  type="button"
                  aria-pressed={active}
                  title={tag.description}
                  onClick={() => onSelect(tag)}
                  className={`rounded-full border px-2 py-0.5 text-xs font-medium transition-colors ${
                    active
                      ? "border-sky-600 bg-sky-600 text-white dark:border-sky-400 dark:bg-sky-400 dark:text-zinc-900"
                      : "border-sky-200 bg-sky-50 text-sky-800 hover:border-sky-400 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300"
                  }`}
                >
                  {tag.label}
                  {tag.direction === "SELL" ? " ↓" : ""}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {!pick && rejection ? (
        <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">{rejection.reason}</p>
      ) : null}
      {horizon === "next_session" ? (
        <p className="mt-2 text-[11px] text-zinc-500 dark:text-zinc-400">
          Monitor only until a live intraday feed is added.
        </p>
      ) : null}
    </div>
  );
}

function StrategyDetail({
  tag,
  pick,
  onBacktest,
  backtestBusy,
}: {
  tag: StrategyTag;
  pick: StockPick | null;
  onBacktest: () => void;
  backtestBusy: boolean;
}) {
  const plan = pick && pick.direction === tag.direction ? pick : null;
  return (
    <div className="space-y-4 rounded-lg border border-sky-200 bg-sky-50/40 p-4 dark:border-sky-900 dark:bg-sky-950/20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">
            Why it&apos;s {tag.label} <span className={DIRECTION_TONE[tag.direction]}>({tag.direction})</span>
          </h3>
          <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{tag.setup?.reason ?? tag.description}</p>
        </div>
        <button
          type="button"
          onClick={onBacktest}
          disabled={backtestBusy}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {backtestBusy ? "Backtesting…" : "Backtest on all history"}
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {pick && !tag.setup ? (
          <section aria-label="Factor scores" className="space-y-2">
            {pick.factors.map((factor) => (
              <FactorRow key={factor.group} factor={factor} />
            ))}
          </section>
        ) : null}
        <div className="space-y-3 text-sm">
          {plan ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              <Item label="Entry" value={`${formatPrice(plan.entry_low)} – ${formatPrice(plan.entry_high)}`} />
              <Item label="Stop" value={formatPrice(tag.setup?.stop ?? plan.stop_loss)} />
              <Item label="Targets" value={plan.targets.map(formatPrice).join(" · ")} />
              <Item label="Risk/reward" value={plan.risk_reward.toFixed(1)} />
              <Item label="Holding" value={plan.holding_period} />
              <Item label="Confidence" value={plan.confidence} />
            </dl>
          ) : tag.setup ? (
            <p className="text-zinc-600 dark:text-zinc-400">
              Stop {formatPrice(tag.setup.stop)}. The engine has no {tag.direction} pick for this horizon,
              so there is no full trade plan; the backtest trades the setup on its own.
            </p>
          ) : null}
          {plan?.reasons.length && !tag.setup ? <List title="Agreeing factors" items={plan.reasons} /> : null}
          {plan ? <List title="Invalidated if" items={plan.invalidation} /> : null}
          {plan ? <List title="Risks" items={plan.risks} /> : null}
        </div>
      </div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">Entry, stop and targets are drawn on the chart below.</p>
    </div>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{title}</h4>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-zinc-700 dark:text-zinc-300">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
