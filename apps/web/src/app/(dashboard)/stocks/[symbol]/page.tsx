import { Suspense } from "react";
import { StockView } from "@/features/stock-overview/stock-view";
import { EXCHANGES, type Exchange } from "@/lib/types";

export const metadata = { title: "Stock" };

type Props = PageProps<"/stocks/[symbol]">;

export default function StockPage({ params, searchParams }: Props) {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>}>
      <StockPageContent params={params} searchParams={searchParams} />
    </Suspense>
  );
}

/** `?exchange=` is NSE or BSE (case-insensitive); anything else falls back to NSE. */
function parseExchange(value: string | string[] | undefined): Exchange {
  const raw = (Array.isArray(value) ? value[0] : value)?.toUpperCase();
  return EXCHANGES.find((exchange) => exchange === raw) ?? "NSE";
}

async function StockPageContent({ params, searchParams }: Pick<Props, "params" | "searchParams">) {
  const [{ symbol }, query] = await Promise.all([params, searchParams]);
  const exchange = parseExchange(query.exchange);
  const normalized = decodeURIComponent(symbol).toUpperCase();
  return <StockView key={`${exchange}:${normalized}`} exchange={exchange} symbol={normalized} />;
}
