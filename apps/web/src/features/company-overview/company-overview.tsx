"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { useAsync } from "@/hooks/use-async";
import { formatDate, formatPrice, formatSigned } from "@/lib/format";
import { getCompanyOverview } from "@/lib/market-api";
import type { CompanyOverview as Overview, Exchange } from "@/lib/types";

const CRORE = 1e7;

/** ₹ amount in crore (lakh crore above 1,00,000 crore), "—" when unknown. */
function inr(value: number | null): string {
  if (value == null) return "—";
  const crore = value / CRORE;
  if (Math.abs(crore) >= 100_000) return `₹${(crore / 100_000).toFixed(2)} lakh cr`;
  return `₹${crore.toLocaleString("en-IN", { maximumFractionDigits: crore < 100 ? 1 : 0 })} cr`;
}
const pct = (fraction: number | null, digits = 1) => (fraction == null ? "—" : `${(fraction * 100).toFixed(digits)}%`);
const signedPct = (fraction: number | null) => (fraction == null ? "—" : `${formatSigned(fraction * 100, 1)}%`);
const ratio = (v: number | null, digits = 1) => (v == null ? "—" : v.toFixed(digits));

/** Stock page: the company's current condition from Yahoo Finance and news-reported orders. */
export function CompanyOverview({ exchange, symbol }: { exchange: Exchange; symbol: string }) {
  const data = useAsync(`company:${exchange}:${symbol}`, (signal) => getCompanyOverview(exchange, symbol, signal));
  return (
    <section aria-labelledby="company-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="company-heading" className="text-lg font-semibold">
          Company
        </h2>
        {data.data?.fundamentals_as_of ? (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Fundamentals as of {formatDate(data.data.fundamentals_as_of)} · Yahoo Finance
          </p>
        ) : null}
      </div>
      {data.error ? (
        <ErrorState title="Couldn't load company data" error={data.error} />
      ) : !data.data ? (
        <LoadingState label="Loading company data…" />
      ) : !data.data.fundamentals_as_of && data.data.annual.length === 0 ? (
        <EmptyState
          title="No fundamentals yet"
          description="Yahoo Finance has no data for this company, or the fundamentals job hasn't run."
        />
      ) : (
        <Body d={data.data} />
      )}
    </section>
  );
}

function Body({ d }: { d: Overview }) {
  const m = d.metrics;
  const peer = d.industry_pe;
  const vsPeer = m.trailing_pe != null && peer.median ? m.trailing_pe / peer.median - 1 : null;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <Group title="Price and valuation">
          <Metric label="Price" value={formatPrice(d.price)} />
          <Metric label="Market cap" value={inr(d.market_cap)} />
          <Metric label="P/E (trailing)" value={ratio(m.trailing_pe)} />
          <Metric
            label={peer.basis ? `${peer.basis === "industry" ? "Industry" : "Sector"} P/E` : "Industry P/E"}
            value={ratio(peer.median)}
            hint={
              peer.median
                ? `Median of ${peer.peers} ${peer.group ?? ""} peers${
                    vsPeer == null ? "" : ` · this stock is ${Math.abs(vsPeer * 100).toFixed(0)}% ${vsPeer >= 0 ? "above" : "below"}`
                  }`
                : "Fewer than 3 peers with a P/E"
            }
          />
          <Metric label="P/E (forward)" value={ratio(m.forward_pe)} />
          <Metric label="Price / book" value={ratio(m.price_to_book)} />
        </Group>
        <Group title="Growth and profit">
          <Metric label="Revenue (TTM)" value={inr(m.revenue_ttm)} />
          <Metric label="Revenue growth (YoY)" value={signedPct(m.revenue_growth)} tone={m.revenue_growth} />
          <Metric label="Net profit (TTM)" value={inr(m.net_income_ttm)} tone={m.net_income_ttm} />
          <Metric label="Profit margin" value={pct(m.profit_margin)} />
          <Metric label="Return on equity" value={pct(m.return_on_equity)} />
        </Group>
        <Group title="Financial health">
          <Metric label="Total debt" value={inr(m.total_debt)} />
          <DebtClearedMetric debt={d.debt_cleared} />
          <Metric label="Cash" value={inr(m.total_cash)} />
          <Metric label="Debt / equity" value={ratio(m.debt_to_equity, 2)} />
          <Metric label="Current ratio" value={ratio(m.current_ratio, 2)} />
          <Metric label="Free cash flow" value={inr(m.free_cash_flow)} tone={m.free_cash_flow} />
        </Group>
        <Group title="Ownership and dividends">
          <Metric label="Promoters / insiders" value={pct(d.ownership.insider_pct)} />
          <Metric label="Institutions" value={pct(d.ownership.institutional_pct)} />
          <Metric
            label="Named holdings (CEO, directors)"
            value="Not available yet"
            hint="Yahoo has no insider roster for NSE stocks"
          />
          <Metric
            label="Dividend, last 12 months"
            value={d.dividends.ttm_per_share == null ? "None" : `₹${d.dividends.ttm_per_share.toFixed(2)} / share`}
            hint={d.dividends.yield_pct == null ? undefined : `Yield ${d.dividends.yield_pct.toFixed(2)}%`}
          />
        </Group>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <AnnualTrend annual={d.annual} />
        <Payouts payouts={d.dividends.payouts} />
      </div>

      <Orders orders={d.orders} />

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Data from Yahoo Finance and news headlines; may be delayed or incomplete. Not investment advice.
      </p>
    </div>
  );
}

const fy = (iso: string) => `FY${String(new Date(iso).getFullYear()).slice(2)}`;

/** Debt paid down from its highest fiscal-year-end level to the latest annual balance sheet. */
function DebtClearedMetric({ debt }: { debt: Overview["debt_cleared"] }) {
  if (!debt) return <Metric label="Debt cleared" value="—" hint="Needs two years of balance sheets" />;
  if (debt.cleared <= 0) {
    return (
      <Metric
        label="Debt cleared"
        value="None"
        tone={-1}
        hint={`Debt at its 4-year high: ${inr(debt.latest)} (${fy(debt.latest_year_end)})`}
      />
    );
  }
  return (
    <Metric
      label="Debt cleared"
      value={`${inr(debt.cleared)} (${debt.cleared_pct.toFixed(0)}%)`}
      tone={1}
      hint={`${inr(debt.peak)} (${fy(debt.peak_year_end)} peak) → ${inr(debt.latest)} (${fy(debt.latest_year_end)})`}
    />
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{title}</h3>
      <dl className="space-y-1.5">{children}</dl>
    </div>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: number | null }) {
  const color =
    tone == null || tone === 0 ? "" : tone > 0 ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500";
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <dt className="text-zinc-600 dark:text-zinc-400">{label}</dt>
      <dd className="text-right">
        <span className={`font-semibold tabular-nums ${color}`}>{value}</span>
        {hint ? <span className="block text-[11px] text-zinc-500 dark:text-zinc-400">{hint}</span> : null}
      </dd>
    </div>
  );
}

/** Revenue and net profit per fiscal year as paired bars. */
function AnnualTrend({ annual }: { annual: Overview["annual"] }) {
  if (annual.length === 0) {
    return <Panel title="Revenue, profit and debt by year"><p className="text-sm text-zinc-500 dark:text-zinc-400">No annual figures.</p></Panel>;
  }
  const max = Math.max(
    1,
    ...annual.flatMap((a) => [Math.abs(a.revenue ?? 0), Math.abs(a.net_income ?? 0), Math.abs(a.total_debt ?? 0)]),
  );
  return (
    <Panel title="Revenue, profit and debt by year">
      <div className="flex items-end gap-4" style={{ height: 140 }}>
        {annual.map((a) => (
          <div key={a.fiscal_year_end} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-[110px] w-full items-end justify-center gap-1">
              <Bar value={a.revenue} max={max} className="bg-sky-500" label={`Revenue ${inr(a.revenue)}`} />
              <Bar
                value={a.net_income}
                max={max}
                className={(a.net_income ?? 0) >= 0 ? "bg-green-500" : "bg-red-500"}
                label={`Net profit ${inr(a.net_income)}`}
              />
              <Bar value={a.total_debt} max={max} className="bg-amber-500" label={`Debt ${inr(a.total_debt)}`} />
            </div>
            <span className="text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
              {fy(a.fiscal_year_end)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 flex gap-4 text-xs text-zinc-500 dark:text-zinc-400">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-sky-500" />Revenue</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-green-500" />Net profit</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-amber-500" />Debt</span>
        <span>Latest: {inr(annual[annual.length - 1].revenue)} / {inr(annual[annual.length - 1].net_income)}</span>
      </p>
    </Panel>
  );
}

function Bar({ value, max, className, label }: { value: number | null; max: number; className: string; label: string }) {
  const h = value == null ? 0 : Math.max(2, (Math.abs(value) / max) * 110);
  return <div title={label} aria-label={label} className={`w-1/4 max-w-5 rounded-t ${className}`} style={{ height: h }} />;
}

function Payouts({ payouts }: { payouts: Overview["dividends"]["payouts"] }) {
  return (
    <Panel title="Dividends paid, last 12 months">
      {payouts.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No dividends in the last 12 months.</p>
      ) : (
        <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
          {payouts.map((p) => (
            <li key={p.ex_date} className="flex justify-between py-1.5 tabular-nums">
              <span>Ex-date {formatDate(p.ex_date)}</span>
              <span className="font-medium">₹{p.amount.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Orders({ orders }: { orders: Overview["orders"] }) {
  return (
    <Panel title="Major orders and projects, last 12 months">
      {orders.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No orders found in recent news.</p>
      ) : (
        <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
          {orders.map((o) => (
            <li key={o.source_url} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2">
              <div className="min-w-0">
                <p className="font-medium">
                  {o.description}
                  {o.counterparty ? <span className="font-normal text-zinc-600 dark:text-zinc-400"> · from {o.counterparty}</span> : null}
                </p>
                <a href={o.source_url} target="_blank" rel="noopener noreferrer" className="line-clamp-1 text-xs text-sky-700 hover:underline dark:text-sky-400">
                  {o.headline}
                </a>
              </div>
              <div className="text-right tabular-nums">
                <span className="font-semibold">{inr(o.value_inr)}</span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">{formatDate(o.reported_on)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
        From news headlines, may be incomplete; check the exchange filing.
      </p>
    </Panel>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{title}</h3>
      {children}
    </div>
  );
}
