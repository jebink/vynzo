"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ExchangeBadge } from "@/components/exchange-badge";
import { formatPrice } from "@/lib/format";
import { stockHref } from "@/lib/routes";
import type { FactorScore, Opportunity } from "@/lib/types";
import { FACTOR_LABELS } from "./horizons";

const DIRECTION_STYLE = {
  BUY: {
    badge: "bg-green-600 text-white dark:bg-green-500 dark:text-zinc-950",
    edge: "border-l-green-600 dark:border-l-green-500",
  },
  SELL: {
    badge: "bg-red-600 text-white dark:bg-red-500 dark:text-zinc-950",
    edge: "border-l-red-600 dark:border-l-red-500",
  },
} as const;

const CONFIDENCE_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };

function priceRange(low: number, high: number) {
  return `${formatPrice(low)} – ${formatPrice(high)}`;
}

/** One ranked pick: the trade plan up front, the reasoning and factor breakdown on demand. */
export function OpportunityCard({ pick }: { pick: Opportunity }) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const style = DIRECTION_STYLE[pick.direction];

  return (
    <article
      className={`rounded-lg border border-l-4 border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950 ${style.edge}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-xs font-bold tracking-wide ${style.badge}`}>
              {pick.direction}
            </span>
            <Link
              href={stockHref(pick.exchange, pick.symbol)}
              className="text-base font-semibold hover:underline"
            >
              {pick.symbol}
            </Link>
            <ExchangeBadge exchange={pick.exchange} />
            {pick.status === "watch" ? (
              <span className="rounded border border-zinc-300 px-1.5 py-px text-[11px] text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                Monitor only
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 truncate text-sm text-zinc-600 dark:text-zinc-400">
            {pick.company_name ?? "—"}
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold leading-none tabular-nums">
            {pick.score}
            <span className="text-sm font-normal text-zinc-500 dark:text-zinc-400">/100</span>
          </p>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{CONFIDENCE_LABEL[pick.confidence]}</p>
        </div>
      </header>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Last close" value={formatPrice(pick.price)} />
        <Stat label="Entry" value={priceRange(pick.entry_low, pick.entry_high)} />
        <Stat label="Stop-loss" value={formatPrice(pick.stop_loss)} tone="text-red-700 dark:text-red-400" />
        <Stat
          label="Targets"
          value={pick.targets.map((t) => formatPrice(t)).join(" · ")}
          tone="text-green-700 dark:text-green-400"
        />
        <Stat label="Risk : reward" value={`1 : ${pick.risk_reward.toFixed(1)}`} />
        <Stat label="Holding" value={pick.holding_period} />
      </dl>

      <ul className="mt-3 space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
        {pick.reasons.slice(0, 3).map((reason) => (
          <li key={reason} className="flex gap-2">
            <span aria-hidden className="text-zinc-400">
              •
            </span>
            <span className="min-w-0">{reason}</span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen((v) => !v)}
        className="mt-3 text-sm font-medium text-zinc-700 underline-offset-4 hover:underline dark:text-zinc-300"
      >
        {open ? "Hide analysis" : "Show full analysis"}
      </button>

      {open ? (
        <div id={detailsId} className="mt-3 grid gap-5 border-t border-zinc-100 pt-4 md:grid-cols-2 dark:border-zinc-800">
          <section aria-label="Factor breakdown" className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Factor breakdown
            </h3>
            {pick.factors.map((factor) => (
              <FactorRow key={factor.group} factor={factor} />
            ))}
          </section>
          <div className="space-y-4 text-sm">
            <LevelList title="Resistance" values={pick.resistances} />
            <LevelList title="Support" values={pick.supports} />
            <TextList title="Invalidated if" items={pick.invalidation} />
            <TextList title="Risks" items={pick.risks} />
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              <Link href={stockHref(pick.exchange, pick.symbol)} className="underline underline-offset-2">
                Open the {pick.symbol} chart
              </Link>{" "}
              · model {pick.calc_version}
            </p>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className={`font-medium tabular-nums ${tone}`}>{value}</dd>
    </div>
  );
}

/** A centred bar from -1 (bearish, left) to +1 (bullish, right). */
function FactorRow({ factor }: { factor: FactorScore }) {
  const width = `${Math.min(1, Math.abs(factor.score)) * 50}%`;
  const bullish = factor.score >= 0;
  return (
    <div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{FACTOR_LABELS[factor.group] ?? factor.group}</span>
        <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
          {factor.score > 0 ? "+" : ""}
          {factor.score.toFixed(2)}
        </span>
      </div>
      <div className="relative mt-1 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800" aria-hidden>
        <div className="absolute inset-y-0 left-1/2 w-px bg-zinc-300 dark:bg-zinc-600" />
        <div
          className={`absolute inset-y-0 rounded-full ${bullish ? "left-1/2 bg-green-500" : "right-1/2 bg-red-500"}`}
          style={{ width }}
        />
      </div>
      <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{factor.reason}</p>
    </div>
  );
}

function LevelList({ title, values }: { title: string; values: number[] }) {
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{title}</h3>
      <p className="mt-1 tabular-nums">{values.length ? values.map((v) => formatPrice(v)).join(" · ") : "None nearby"}</p>
    </div>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{title}</h3>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-zinc-700 dark:text-zinc-300">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
