import type { Exchange } from "@/lib/types";

/** The stock page for a listing, e.g. `/stocks/RELIANCE?exchange=NSE`. */
export function stockHref(exchange: Exchange, symbol: string) {
  return `/stocks/${encodeURIComponent(symbol)}?exchange=${exchange}` as const;
}
