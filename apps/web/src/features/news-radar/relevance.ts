// Pure ranking for the dashboard news radar (no imports, so `node --test` can load it directly).

export interface Rankable {
  score: number; // -1..+1
  confidence: number | null; // 0..1
  latest: string | null; // ISO time of the newest headline
}

/** Newest headline day first; within a day, the strongest confident story (|score| x confidence). */
export function rankByRelevance<T extends Rankable>(items: readonly T[]): T[] {
  const day = (t: T) => t.latest?.slice(0, 10) ?? "";
  const weight = (t: T) => Math.abs(t.score) * (t.confidence ?? 0);
  return [...items].sort((a, b) => day(b).localeCompare(day(a)) || weight(b) - weight(a));
}
