import assert from "node:assert/strict";
import { test } from "node:test";

import { rankByRelevance } from "./relevance.ts";

test("newest day first, then |score| x confidence", () => {
  const items = [
    { id: "old-strong", score: 0.9, confidence: 1, latest: "2026-11-12T10:00:00Z" },
    { id: "new-weak", score: 0.1, confidence: 0.5, latest: "2026-11-14T09:00:00Z" },
    { id: "new-bearish", score: -0.8, confidence: 0.9, latest: "2026-11-14T01:00:00Z" },
    { id: "no-date", score: 1, confidence: 1, latest: null },
  ];
  assert.deepEqual(rankByRelevance(items).map((i) => i.id), ["new-bearish", "new-weak", "old-strong", "no-date"]);
});
