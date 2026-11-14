import { MarketOpportunities } from "@/features/opportunities/market-opportunities";
import { StockSearch } from "@/features/stock-search/stock-search";

export const metadata = { title: "Market" };

export default function MarketPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Market</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            The strongest BUY and SELL candidates for intraday, swing and long-term trading,
            ranked by a multi-factor score.
          </p>
        </div>
        <StockSearch />
      </div>
      <MarketOpportunities />
    </div>
  );
}
