import { humanizeSignalType } from "@/lib/format";
import { HIGH_VOLUME_BUY } from "@/lib/types";

const TONES: Record<string, string> = {
  [HIGH_VOLUME_BUY]:
    "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-400/20",
  SENTIMENT:
    "bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-950/50 dark:text-violet-300 dark:ring-violet-400/20",
};

const DEFAULT_TONE =
  "bg-zinc-100 text-zinc-700 ring-zinc-500/20 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-400/20";

export function SignalTypeBadge({ type }: { type: string }) {
  return (
    <span
      title={type}
      className={`inline-flex whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[type] ?? DEFAULT_TONE}`}
    >
      {humanizeSignalType(type)}
    </span>
  );
}
