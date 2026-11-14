export function ExchangeBadge({ exchange }: { exchange: string }) {
  return (
    <span className="inline-flex rounded border border-zinc-300 px-1 py-px text-[10px] font-semibold tracking-wide text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
      {exchange}
    </span>
  );
}
