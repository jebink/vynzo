import { SignalFeed } from "@/features/signals/components/signal-feed";
import { StockSearch } from "@/features/stock-search/stock-search";

export const metadata = { title: "Markets · Signals" };

export default function MarketsPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">Markets</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Find a stock or browse the latest signals from the daily scan.
          </p>
        </div>
        <StockSearch />
      </div>
      <SignalFeed />
    </div>
  );
}
