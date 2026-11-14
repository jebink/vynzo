"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { formatDate, formatPrice, formatSigned } from "@/lib/format";
import { streamBacktest } from "@/lib/market-api";
import type { BacktestSummary, BacktestTrade, Exchange } from "@/lib/types";

/** Sweep length of the replay; the cursor never runs ahead of the data actually received. */
const SWEEP_MS = 5000;

export interface BacktestRun {
  status: "idle" | "running" | "done" | "error";
  first: string | null;
  last: string | null;
  through: string | null;
  trades: BacktestTrade[];
  summary: Record<string, BacktestSummary> | null;
  error: string | null;
}

const IDLE: BacktestRun = {
  status: "idle",
  first: null,
  last: null,
  through: null,
  trades: [],
  summary: null,
  error: null,
};

/** One full-history backtest per stock covers every strategy; `start` is a no-op once running.
 * Mount it per stock (key the owner by stock) so a new stock starts from idle. */
export function useBacktest(exchange: Exchange, symbol: string) {
  const [run, setRun] = useState<BacktestRun>(IDLE);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useCallback(() => {
    if (abortRef.current && !abortRef.current.signal.aborted) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRun({ ...IDLE, status: "running" });
    streamBacktest(
      exchange,
      symbol,
      (event) =>
        setRun((prev) => {
          if (event.type === "start") return { ...prev, first: event.first, last: event.last };
          if (event.type === "progress") {
            return { ...prev, through: event.through, trades: [...prev.trades, ...event.trades] };
          }
          return { ...prev, status: "done", through: prev.last, summary: event.summary };
        }),
      controller.signal,
    ).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      abortRef.current = null;
      setRun((prev) => ({ ...prev, status: "error", error: String(error) }));
    });
  }, [exchange, symbol]);

  return { run, start };
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onChange: () => void): () => void {
  const media = window.matchMedia(REDUCED_MOTION);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

const time = (iso: string | null) => (iso ? Date.parse(iso) : NaN);
const tradeTime = (t: BacktestTrade) => time(t.exit_at ?? t.as_of);
const entered = (t: BacktestTrade) =>
  t.return_pct != null && (t.outcome === "target_hit" || t.outcome === "stopped" || t.outcome === "expired");

/** Replay of one strategy's backtest: a cursor sweeps the stock's history, each trade lands as
 * the cursor passes its exit, and the equity curve grows behind it. Then the results.
 * Remount (key) it to restart the sweep. */
export function BacktestReplay({
  run,
  strategy,
  label,
  animate,
  onReplay,
}: {
  run: BacktestRun;
  strategy: string;
  label: string;
  animate: boolean;
  onReplay: () => void;
}) {
  const reduced = usePrefersReducedMotion();
  const [elapsed, setElapsed] = useState(animate ? 0 : SWEEP_MS);
  const [skipped, setSkipped] = useState(false);

  useEffect(() => {
    if (!animate) return;
    const begin = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      setElapsed(now - begin);
      if (now - begin < SWEEP_MS) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [animate]);

  const t0 = time(run.first);
  const t1 = time(run.last);
  const span = t1 - t0 || 1;
  // Before the start event the date range is unknown (NaN): treat it as no progress yet.
  const sofar = (time(run.through) - t0) / span;
  const received = run.status === "done" ? 1 : Number.isFinite(sofar) ? Math.max(0, sofar) : 0;
  const progress = reduced || skipped ? received : Math.min(received, elapsed / SWEEP_MS);
  const cursor = t0 + progress * span;
  const finished = run.status === "done" && progress >= 1;

  const mine = useMemo(() => run.trades.filter((t) => t.strategy === strategy), [run.trades, strategy]);
  const shown = mine.filter((t) => tradeTime(t) <= cursor);
  const live = liveStats(shown);

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Backtest · {label}</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Walk-forward over every session from {formatDate(run.first)} to {formatDate(run.last)}: the
            model only sees bars up to each day.
          </p>
        </div>
        {finished ? (
          <button type="button" onClick={onReplay} className={BUTTON}>
            Replay
          </button>
        ) : (
          <button type="button" onClick={() => setSkipped(true)} className={BUTTON}>
            Skip animation
          </button>
        )}
      </div>

      <div aria-live="polite" className="grid grid-cols-2 gap-2 text-center sm:grid-cols-4">
        <Counter label="Trades" value={String(shown.length)} />
        <Counter label="Win rate" value={live.winRate == null ? "—" : `${Math.round(live.winRate * 100)}%`} />
        <Counter
          label="Compounded"
          value={live.total == null ? "—" : `${formatSigned(live.total, 1)}%`}
          tone={live.total == null ? undefined : live.total >= 0 ? "up" : "down"}
        />
        <Counter label="Losses" value={String(live.losses)} tone={live.losses ? "down" : undefined} />
      </div>

      <ReplayChart trades={shown} t0={t0} span={span} cursor={progress} active={!finished} />

      <LossBreakdown trades={shown} />

      {run.status === "running" && received < progress + 0.001 ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Scoring {formatDate(run.through ?? run.first)}… a full history takes up to half a minute the
          first time.
        </p>
      ) : null}

      {finished && run.summary ? <Results summary={run.summary[strategy]} trades={mine} /> : null}
    </div>
  );
}

const BUTTON =
  "rounded-md border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800";

function liveStats(trades: BacktestTrade[]) {
  const done = trades.filter(entered);
  const losses = done.filter((t) => (t.return_pct ?? 0) < 0).length;
  if (!done.length) return { winRate: null, total: null, losses };
  const curve = equityPoints(done);
  return {
    losses,
    winRate: done.filter((t) => (t.return_pct ?? 0) > 0).length / done.length,
    total: (curve[curve.length - 1].e - 1) * 100,
  };
}

/** Growth of 1 compounding entered trades in exit order (the API's equity_curve formula). */
function equityPoints(trades: BacktestTrade[]): { t: number; e: number }[] {
  const sorted = trades.filter(entered).sort((a, b) => tradeTime(a) - tradeTime(b));
  const out: { t: number; e: number }[] = [];
  let equity = 1;
  for (const t of sorted) {
    equity *= 1 + (t.return_pct ?? 0) / 100;
    out.push({ t: tradeTime(t), e: equity });
  }
  return out;
}

function Counter({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  const color =
    tone === "up" ? "text-green-600 dark:text-green-500" : tone === "down" ? "text-red-600 dark:text-red-500" : "";
  return (
    <div className="rounded-md bg-zinc-50 px-2 py-2 dark:bg-zinc-900">
      <p className={`text-lg font-semibold tabular-nums ${color}`}>{value}</p>
      <p className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{label}</p>
    </div>
  );
}

const W = 800;
const RET_TOP = 12;
const RET_H = 150;
const EQ_TOP = 190;
const EQ_H = 70;

/** Hover card for one trade: when it was taken and its entry and exit prices. */
function TradeTooltip({ trade }: { trade: BacktestTrade }) {
  const r = trade.return_pct;
  const tone = r == null ? "" : r >= 0 ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500";
  return (
    <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs tabular-nums">
      <dt className="text-zinc-500 dark:text-zinc-400">Signal</dt>
      <dd className="font-medium">
        {trade.direction} · {formatDate(trade.as_of)}
      </dd>
      <dt className="text-zinc-500 dark:text-zinc-400">Entry</dt>
      <dd>{trade.entry_at ? `${formatDate(trade.entry_at)} @ ${formatPrice(trade.entry_price)}` : "Not filled"}</dd>
      <dt className="text-zinc-500 dark:text-zinc-400">Exit</dt>
      <dd>{trade.exit_at ? `${formatDate(trade.exit_at)} @ ${formatPrice(trade.exit_price)}` : "—"}</dd>
      <dt className="text-zinc-500 dark:text-zinc-400">Result</dt>
      <dd className={`font-semibold ${tone}`}>
        {r == null ? OUTCOME_LABEL[trade.outcome] : `${formatSigned(r, 1)}% · ${OUTCOME_LABEL[trade.outcome]}`}
      </dd>
      {trade.loss_reasons?.length ? (
        <>
          <dt className="text-zinc-500 dark:text-zinc-400">Why</dt>
          <dd>
            <ul className="max-w-64 list-disc space-y-0.5 pl-4 whitespace-normal">
              {trade.loss_reasons.map((reason) => (
                <li key={reason.code}>{reason.text}</li>
              ))}
            </ul>
          </dd>
        </>
      ) : null}
    </dl>
  );
}

/** Hover snaps to the nearest trade within this many chart units (of W). */
const HOVER_RADIUS = 14;

/** Top: each trade's return as a lollipop at its exit date. Bottom: the compounded equity curve.
 * Hovering (while playing or after) shows the nearest trade's dates and prices. */
function ReplayChart({
  trades,
  t0,
  span,
  cursor,
  active,
}: {
  trades: BacktestTrade[];
  t0: number;
  span: number;
  cursor: number;
  active: boolean;
}) {
  const [hover, setHover] = useState<{ key: string; px: number } | null>(null);
  const x = (ms: number) => ((ms - t0) / span) * W;
  const keyOf = (t: BacktestTrade) => `${t.as_of}:${t.direction}`;
  const hovered = hover ? trades.find((t) => keyOf(t) === hover.key) ?? null : null;

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * W;
    let best: BacktestTrade | null = null;
    for (const t of trades) {
      const d = Math.abs(x(tradeTime(t)) - px);
      if (d <= HOVER_RADIUS && (best === null || d < Math.abs(x(tradeTime(best)) - px))) best = t;
    }
    setHover(best ? { key: keyOf(best), px: x(tradeTime(best)) } : null);
  };
  const maxAbs = Math.max(5, ...trades.map((t) => Math.abs(t.return_pct ?? 0)));
  const zero = RET_TOP + RET_H / 2;
  const y = (r: number) => zero - (Math.max(-maxAbs, Math.min(maxAbs, r)) / maxAbs) * (RET_H / 2);

  const points = equityPoints(trades);
  const lo = Math.min(1, ...points.map((p) => p.e));
  const hi = Math.max(1, ...points.map((p) => p.e));
  const ey = (e: number) => EQ_TOP + EQ_H - ((e - lo) / (hi - lo || 1)) * EQ_H;
  const path = [`M0,${ey(1)}`, ...points.map((p) => `L${x(p.t).toFixed(1)},${ey(p.e).toFixed(1)}`)];
  if (points.length) path.push(`L${(cursor * W).toFixed(1)},${ey(points[points.length - 1].e).toFixed(1)}`);

  return (
    <div className="relative">
    <svg
      viewBox={`0 0 ${W} ${EQ_TOP + EQ_H + 6}`}
      className="h-auto w-full touch-none"
      role="img"
      aria-label={`Backtest replay: ${trades.length} trades so far. Hover a trade for its dates and prices.`}
      onPointerMove={onPointerMove}
      onPointerLeave={() => setHover(null)}
    >
      <style>{`
        @keyframes bt-pop { from { transform: scale(0); opacity: 0 } to { transform: scale(1); opacity: 1 } }
        .bt-trade { transform-box: fill-box; transform-origin: bottom; animation: bt-pop 380ms cubic-bezier(.2,1.4,.4,1) both }
        @media (prefers-reduced-motion: reduce) { .bt-trade { animation: none } }
      `}</style>
      <line x1={0} x2={W} y1={zero} y2={zero} className="stroke-zinc-300 dark:stroke-zinc-700" strokeDasharray="4 4" />
      <text x={4} y={RET_TOP + 10} className="fill-zinc-400 text-[11px]">
        +{maxAbs.toFixed(0)}%
      </text>
      <text x={4} y={RET_TOP + RET_H} className="fill-zinc-400 text-[11px]">
        −{maxAbs.toFixed(0)}%
      </text>
      {trades.map((t) => {
        const r = t.return_pct;
        const cx = x(tradeTime(t));
        const color = r == null ? "#a1a1aa" : r >= 0 ? "#16a34a" : "#dc2626";
        return (
          <g key={keyOf(t)} className="bt-trade">
            <line x1={cx} x2={cx} y1={zero} y2={y(r ?? 0)} stroke={color} strokeWidth={2} />
            <circle
              cx={cx}
              cy={y(r ?? 0)}
              r={hover?.key === keyOf(t) ? 6 : 3.5}
              fill={color}
              className={hover?.key === keyOf(t) ? "stroke-white dark:stroke-zinc-900" : undefined}
              strokeWidth={2}
            />
          </g>
        );
      })}
      <text x={4} y={EQ_TOP - 4} className="fill-zinc-400 text-[11px]">
        Equity (compounded)
      </text>
      <path d={path.join(" ")} fill="none" stroke="#0284c7" strokeWidth={2} strokeLinejoin="round" />
      {hovered && hover ? (
        <line x1={hover.px} x2={hover.px} y1={0} y2={EQ_TOP + EQ_H} className="stroke-zinc-400 dark:stroke-zinc-500" strokeDasharray="2 3" />
      ) : null}
      {active ? (
        <g>
          <line x1={cursor * W} x2={cursor * W} y1={0} y2={EQ_TOP + EQ_H} stroke="#0ea5e9" strokeWidth={6} opacity={0.15} />
          <line x1={cursor * W} x2={cursor * W} y1={0} y2={EQ_TOP + EQ_H} stroke="#0ea5e9" strokeWidth={1.5} />
        </g>
      ) : null}
    </svg>
      {hovered && hover ? (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-md border border-zinc-200 bg-white px-3 py-2 shadow-md dark:border-zinc-700 dark:bg-zinc-900"
          style={
            hover.px > W / 2
              ? { right: `${100 - (hover.px / W) * 100 + 1}%` }
              : { left: `${(hover.px / W) * 100 + 1}%` }
          }
        >
          <TradeTooltip trade={hovered} />
        </div>
      ) : null}
    </div>
  );
}

/** Short names for the loss causes the backtest measures (analytics_worker diagnosis.py). */
const REASON_LABEL: Record<string, string> = {
  gap_through_stop: "Gapped through stop",
  tight_stop: "Stop inside daily noise",
  gave_back_profit: "Gave back open profit",
  against_regime: "Against market regime",
  market_drag: "Market-wide drop",
  chased_entry: "Chased an extended move",
  volatility_spike: "Entered in a volatility spike",
  no_follow_through: "No follow-through",
  stock_specific: "Stock-specific move",
};

/** What to try when a cause dominates: the strategy gap it points to. */
const REASON_FIX: Record<string, string> = {
  gap_through_stop: "losses run past the stop; size positions for gap risk",
  tight_stop: "widen the stop to at least 1 ATR",
  gave_back_profit: "add a trailing stop or take partial profit",
  against_regime: "skip signals that fight the market regime",
  market_drag: "add a NIFTY trend filter",
  chased_entry: "wait for a pullback toward the 20-day average",
  volatility_spike: "skip or size down when volatility is unusually high",
  no_follow_through: "shorten the time limit or demand momentum confirmation",
  stock_specific: "check news and results dates before entering",
};

/** Live tally of why losing trades lost, so the strategy's weak spot shows as the replay runs.
 * A trade can have several causes, so the shares can add up to more than 100%. */
function LossBreakdown({ trades }: { trades: BacktestTrade[] }) {
  const losers = trades.filter((t) => entered(t) && (t.return_pct ?? 0) < 0);
  const counts = new Map<string, number>();
  for (const t of losers) for (const r of t.loss_reasons ?? []) counts.set(r.code, (counts.get(r.code) ?? 0) + 1);
  const rows = [...counts].sort((a, b) => b[1] - a[1]);
  if (!losers.length || !rows.length) return null;
  const [topCode] = rows[0];
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold">
        Why trades lost <span className="font-normal text-zinc-500 dark:text-zinc-400">({losers.length} losing trades)</span>
      </h4>
      <ul className="space-y-1.5">
        {rows.map(([code, n]) => {
          const share = n / losers.length;
          return (
            <li key={code} className="grid grid-cols-[11rem_1fr_3rem] items-center gap-2 text-xs">
              <span className="truncate">{REASON_LABEL[code] ?? code}</span>
              <span className="h-2 rounded-full bg-zinc-100 dark:bg-zinc-800">
                <span
                  className="block h-2 rounded-full bg-red-500/70 transition-[width] duration-300"
                  style={{ width: `${Math.round(share * 100)}%` }}
                />
              </span>
              <span className="text-right tabular-nums text-zinc-500 dark:text-zinc-400">{Math.round(share * 100)}%</span>
            </li>
          );
        })}
      </ul>
      {REASON_FIX[topCode] ? (
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
          Biggest gap: <span className="font-medium">{REASON_LABEL[topCode]}</span>. Try: {REASON_FIX[topCode]}.
        </p>
      ) : null}
    </div>
  );
}

const OUTCOME_LABEL: Record<BacktestTrade["outcome"], string> = {
  target_hit: "Target hit",
  stopped: "Stopped",
  expired: "Time exit",
  not_triggered: "Not triggered",
  open: "Open",
};

const pct = (v: number | null, digits = 1) => (v == null ? "—" : `${formatSigned(v, digits)}%`);
const rate = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

type TradeSort = "date" | "return";
const SORT_OPTIONS = [
  { value: "date", label: "Newest" },
  { value: "return", label: "Best return" },
] as const;

function Results({ summary, trades }: { summary: BacktestSummary | undefined; trades: BacktestTrade[] }) {
  const [sort, setSort] = useState<TradeSort>("date");
  if (!summary || summary.picks === 0) {
    return (
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        This strategy never triggered on this stock in the available history.
      </p>
    );
  }
  const rows = [...trades].sort((a, b) =>
    sort === "date" ? b.as_of.localeCompare(a.as_of) : (b.return_pct ?? -Infinity) - (a.return_pct ?? -Infinity),
  );
  const stats = [
    { label: "Signals", value: String(summary.picks) },
    { label: "Entered", value: String(summary.entered) },
    { label: "Win rate", value: rate(summary.win_rate) },
    { label: "Target hit", value: rate(summary.hit_rate) },
    { label: "Avg return", value: pct(summary.avg_return_pct, 2) },
    { label: "Median", value: pct(summary.median_return_pct, 2) },
    { label: "Compounded", value: pct(summary.total_return_pct) },
    { label: "Max drawdown", value: summary.max_drawdown_pct == null ? "—" : `−${summary.max_drawdown_pct.toFixed(1)}%` },
    { label: "Vs NIFTY / trade", value: pct(summary.excess_vs_nifty_pct, 2) },
    { label: "Avg hold", value: summary.avg_sessions_held == null ? "—" : `${summary.avg_sessions_held.toFixed(0)} sessions` },
  ];
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label}>
            <dt className="text-xs text-zinc-500 dark:text-zinc-400">{s.label}</dt>
            <dd className="font-semibold tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">Trades</h4>
        <SegmentedControl label="Sort trades" options={SORT_OPTIONS} value={sort} onChange={setSort} />
      </div>
      <div className="max-h-80 overflow-auto rounded-md border border-zinc-200 dark:border-zinc-800">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="sticky top-0 bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
            <tr>
              <th className="px-3 py-2 font-medium">Signal</th>
              <th className="px-3 py-2 font-medium">Side</th>
              <th className="px-3 py-2 text-right font-medium">Entry</th>
              <th className="px-3 py-2 text-right font-medium">Exit</th>
              <th className="px-3 py-2 font-medium">Outcome</th>
              <th className="px-3 py-2 text-right font-medium">Return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {rows.map((t) => (
              <tr key={`${t.as_of}:${t.direction}`}>
                <td className="px-3 py-1.5 tabular-nums">{formatDate(t.as_of)}</td>
                <td className="px-3 py-1.5">{t.direction}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(t.entry_price)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(t.exit_price)}</td>
                <td className="px-3 py-1.5">
                  {OUTCOME_LABEL[t.outcome]}
                  {t.loss_reasons?.length ? (
                    <div className="text-xs text-zinc-500 dark:text-zinc-400">
                      {t.loss_reasons.map((reason) => REASON_LABEL[reason.code] ?? reason.code).join(" · ")}
                    </div>
                  ) : null}
                </td>
                <td
                  className={`px-3 py-1.5 text-right font-medium tabular-nums ${
                    t.return_pct == null ? "" : t.return_pct >= 0 ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500"
                  }`}
                >
                  {pct(t.return_pct, 2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Each signal is traded on its own: entry within the plan&apos;s range, its stop, the first target,
        or the horizon&apos;s time limit. No costs, slippage or taxes; today&apos;s listings only
        (survivorship). Compounded return chains trades one after another. Past results don&apos;t
        predict future ones.
      </p>
    </div>
  );
}

