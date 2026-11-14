import { ExchangeBadge } from "@/components/exchange-badge";
import { formatDate, formatPrice, formatSigned } from "@/lib/format";
import type { ListingDetail } from "@/lib/types";

/** Symbol, company, exchange and the last close with its change vs the previous close. */
export function StockHeader({ listing }: { listing: ListingDetail }) {
  const { latest, previous_close: previousClose } = listing;
  const change = latest && previousClose != null ? latest.close - previousClose : null;
  const changePct = change != null && previousClose ? (change / previousClose) * 100 : null;
  const tone =
    change == null || change === 0
      ? "text-zinc-600 dark:text-zinc-400"
      : change > 0
        ? "text-green-600 dark:text-green-500"
        : "text-red-600 dark:text-red-500";

  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{listing.symbol}</h1>
          <ExchangeBadge exchange={listing.exchange} />
          {!listing.is_active ? (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">(not in daily scan)</span>
          ) : null}
        </div>
        <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">{listing.company_name}</p>
      </div>
      {latest ? (
        <div className="text-right">
          <p className="text-2xl font-semibold tabular-nums">{formatPrice(latest.close)}</p>
          <p className={`text-sm font-medium tabular-nums ${tone}`}>
            {change != null ? formatSigned(change) : "—"}
            {changePct != null ? ` (${formatSigned(changePct)}%)` : ""}
          </p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Close on {formatDate(latest.ts)}</p>
        </div>
      ) : (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No price data yet</p>
      )}
    </header>
  );
}

export function StockHeaderSkeleton({ symbol, exchange }: { symbol: string; exchange: string }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4" aria-busy>
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{symbol}</h1>
          <ExchangeBadge exchange={exchange} />
        </div>
        <div className="mt-1.5 h-4 w-56 animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />
      </div>
      <div className="space-y-1.5">
        <div className="ml-auto h-7 w-28 animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />
        <div className="ml-auto h-4 w-20 animate-pulse rounded bg-zinc-100 dark:bg-zinc-800" />
      </div>
    </header>
  );
}
