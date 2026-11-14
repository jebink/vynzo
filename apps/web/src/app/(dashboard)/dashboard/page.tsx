import Link from "next/link";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <section className="max-w-xl rounded-lg border border-zinc-200 p-5 dark:border-zinc-800">
        <h2 className="font-semibold">Markets &amp; signals</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Search NSE and BSE stocks, open candlestick charts with EMA and RSI overlays, and browse
          the daily signal feed, such as high-volume buys.
        </p>
        <Link
          href="/markets"
          className="mt-4 inline-flex rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Open the signal feed →
        </Link>
      </section>
    </div>
  );
}
