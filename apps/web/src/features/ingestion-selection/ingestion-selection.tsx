"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { SegmentedControl } from "@/components/segmented-control";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { Switch } from "@/components/switch";
import { useAsync } from "@/hooks/use-async";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { formatDate } from "@/lib/format";
import { getSelection, setSelection } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import { EXCHANGES, type Exchange, type ListingState, type SelectionRow, type SelectionStatus } from "@/lib/types";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 250;

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "selected", label: "Selected" },
  { value: "unselected", label: "Not selected" },
] as const;

const listingOf = (row: SelectionRow, exchange: Exchange) => (exchange === "NSE" ? row.nse : row.bse);

/**
 * Choose which companies, on which exchange, the daily pipeline ingests. Each switch sets one
 * listing's selection on the server; the change applies from the next daily run.
 */
export function IngestionSelection() {
  const inputId = useId();
  const [text, setText] = useState("");
  const [status, setStatus] = useState<SelectionStatus>("all");
  const [offset, setOffset] = useState(0);
  // Rows as returned by successful switch changes, newer than the fetched page.
  const [updated, setUpdated] = useState<Record<string, SelectionRow>>({});

  const q = useDebouncedValue(text.trim(), DEBOUNCE_MS);
  const page = useAsync(`selection:${q}:${status}:${offset}`, (signal) =>
    getSelection({ q, status, offset, limit: PAGE_SIZE }, signal),
  );

  const rows = page.data?.rows.map((row) => updated[row.symbol] ?? row) ?? [];

  // Server counts, adjusted for switches changed since this page was fetched.
  const selected = { ...(page.data?.selected ?? { NSE: 0, BSE: 0 }) };
  for (const fetched of page.data?.rows ?? []) {
    const current = updated[fetched.symbol];
    if (!current) continue;
    for (const exchange of EXCHANGES) {
      selected[exchange] +=
        Number(listingOf(current, exchange)?.is_active ?? false) -
        Number(listingOf(fetched, exchange)?.is_active ?? false);
    }
  }

  function resetPaging<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setOffset(0);
    };
  }

  const total = page.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Daily ingestion</h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Choose the companies and exchanges the daily job fetches. It runs Monday to Friday at
          17:00 IST, then computes indicators and signals for the selected listings. A newly
          selected listing gets its full price history on its first run. Deselecting stops new data
          and keeps the history.
        </p>
        {page.data ? (
          <p className="text-sm font-medium tabular-nums">
            {selected.NSE + selected.BSE} listings selected
            <span className="font-normal text-zinc-500 dark:text-zinc-400">
              {" "}
              · NSE {selected.NSE} · BSE {selected.BSE}
            </span>
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={inputId} className="sr-only">
          Search companies
        </label>
        <input
          id={inputId}
          type="search"
          autoComplete="off"
          placeholder="Search by symbol or company…"
          value={text}
          onChange={(event) => resetPaging(setText)(event.target.value)}
          className="w-full max-w-xs rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none placeholder:text-zinc-400 focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:placeholder:text-zinc-500 dark:focus:border-zinc-500 dark:focus:ring-zinc-800"
        />
        <SegmentedControl label="Show" options={STATUS_OPTIONS} value={status} onChange={resetPaging(setStatus)} />
      </div>

      {page.error ? (
        <ErrorState title="Couldn't load companies" error={page.error} />
      ) : !page.data ? (
        <LoadingState label="Loading companies…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No companies match this filter" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="w-full min-w-[680px] text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Company</th>
                  {EXCHANGES.map((exchange) => (
                    <th key={exchange} scope="col" className="w-56 px-3 py-2 font-medium">
                      {exchange}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {rows.map((row) => (
                  <CompanyRow
                    key={row.symbol}
                    row={row}
                    onUpdated={(next) => setUpdated((prev) => ({ ...prev, [next.symbol]: next }))}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} total={total} shown={rows.length} onChange={setOffset} />
        </>
      )}

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        BSE uses the company&apos;s NSE symbol with Yahoo&apos;s <code>.BO</code> suffix. If the
        company trades under a different symbol on BSE, its fetch fails and is logged in the
        ingestion runs. There is no login yet: anyone who can open this page can change the
        selection.
      </p>
    </div>
  );
}

function CompanyRow({ row, onUpdated }: { row: SelectionRow; onUpdated: (row: SelectionRow) => void }) {
  const primary: Exchange = row.nse ? "NSE" : "BSE";
  return (
    <tr className="align-top">
      <td className="max-w-[320px] px-3 py-2.5">
        <Link href={stockHref(primary, row.symbol)} className="font-semibold hover:underline">
          {row.symbol}
        </Link>
        {row.kind === "index" ? (
          <span className="ml-2 text-[10px] uppercase tracking-wide text-zinc-400">Index</span>
        ) : null}
        <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400">
          {row.company_name ?? "No company linked"}
          {row.isin ? ` · ${row.isin}` : ""}
        </span>
      </td>
      {EXCHANGES.map((exchange) => (
        <ListingCell key={exchange} row={row} exchange={exchange} onUpdated={onUpdated} />
      ))}
    </tr>
  );
}

function ListingCell({
  row,
  exchange,
  onUpdated,
}: {
  row: SelectionRow;
  exchange: Exchange;
  onUpdated: (row: SelectionRow) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listing = listingOf(row, exchange);
  // A missing listing can only be created for a company (not an index or unlinked listing).
  const canCreate = row.kind === "equity" && row.company_name !== null;
  const unavailable = listing === null && !canCreate;

  async function toggle(next: boolean) {
    setSaving(true);
    setError(null);
    try {
      onUpdated(await setSelection(exchange, row.symbol, next));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <td className="px-3 py-2.5">
      <div className="flex items-start gap-3">
        <Switch
          checked={listing?.is_active ?? false}
          onChange={toggle}
          disabled={saving || unavailable}
          label={`Ingest ${row.symbol} on ${exchange}`}
          title={unavailable ? `No company linked, so ${row.symbol} can't be added on ${exchange}` : undefined}
        />
        <div className="min-w-0 text-xs leading-5">
          {saving ? (
            <span className="text-zinc-500 dark:text-zinc-400">Saving…</span>
          ) : error ? (
            <span role="alert" className="text-red-600 dark:text-red-400">
              {error}
            </span>
          ) : (
            <ListingStatus listing={listing} unavailable={unavailable} />
          )}
        </div>
      </div>
    </td>
  );
}

function ListingStatus({ listing, unavailable }: { listing: ListingState | null; unavailable: boolean }) {
  const muted = "text-zinc-500 dark:text-zinc-400";
  if (listing === null) {
    return <span className={muted}>{unavailable ? "Not available" : "Not listed yet"}</span>;
  }
  if (listing.is_active) {
    return listing.last_bar ? (
      <span className="text-zinc-700 dark:text-zinc-300">Last bar {formatDate(listing.last_bar)}</span>
    ) : (
      <span className="text-amber-700 dark:text-amber-400">First fetch on next run</span>
    );
  }
  return (
    <span className={muted}>{listing.last_bar ? `Paused · data to ${formatDate(listing.last_bar)}` : "Off"}</span>
  );
}

function Pager({
  offset,
  total,
  shown,
  onChange,
}: {
  offset: number;
  total: number;
  shown: number;
  onChange: (offset: number) => void;
}) {
  const button =
    "rounded-md border border-zinc-300 px-3 py-1 text-sm font-medium hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-900";
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <p className="text-zinc-500 tabular-nums dark:text-zinc-400">
        {offset + 1}–{offset + shown} of {total.toLocaleString("en-IN")}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className={button}
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          className={button}
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => onChange(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
