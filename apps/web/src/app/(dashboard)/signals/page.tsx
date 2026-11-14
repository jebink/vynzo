import { SignalsOpportunities } from "@/features/opportunities/signals-opportunities";
import { StockSearch } from "@/features/stock-search/stock-search";

export const metadata = { title: "Signals" };

export default function SignalsPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Signals</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            The strongest BUY and SELL candidates for intraday, swing and long-term trading,
            ranked by a multi-factor score.
          </p>
        </div>
        <StockSearch />
      </div>
      <SignalsOpportunities />
    </div>
  );
}
