// Market cap and sector filters shared by the Market and Stocks screens.
import type { CapCategory } from "@/lib/types";

export type CapFilter = "all" | CapCategory;

export const CAP_OPTIONS = [
  { value: "all", label: "All" },
  { value: "large", label: "Large" },
  { value: "mid", label: "Mid" },
  { value: "small", label: "Small" },
] as const;

type Classified = { sector: string | null; cap_category: CapCategory | null };

export function matchesCompany(item: Classified, cap: CapFilter, sector: string): boolean {
  return (cap === "all" || item.cap_category === cap) && (sector === "any" || item.sector === sector);
}

/** Sector dropdown (Yahoo Finance sectors) listing only the sectors present in `items`, with counts. */
export function SectorSelect({
  items,
  value,
  onChange,
}: {
  items: Classified[];
  value: string;
  onChange: (value: string) => void;
}) {
  const counts = new Map<string, number>();
  for (const item of items) if (item.sector) counts.set(item.sector, (counts.get(item.sector) ?? 0) + 1);
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-zinc-600 dark:text-zinc-400">Sector</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
      >
        <option value="any">Any</option>
        {[...counts.keys()].sort().map((name) => (
          <option key={name} value={name}>
            {name} ({counts.get(name)})
          </option>
        ))}
      </select>
    </label>
  );
}
