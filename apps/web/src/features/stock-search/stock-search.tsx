"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { ExchangeBadge } from "@/components/exchange-badge";
import { useAsync } from "@/hooks/use-async";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { searchListings } from "@/lib/market-api";
import { stockHref } from "@/lib/routes";
import type { Listing } from "@/lib/types";

const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 10;

/** Debounced stock picker; choosing a result opens its stock page. */
export function StockSearch() {
  const router = useRouter();
  const listboxId = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState({ query: "", index: 0 });

  const query = useDebouncedValue(text.trim(), DEBOUNCE_MS);
  const search = useAsync(query ? `search:${query}` : null, (signal) =>
    searchListings({ q: query, limit: RESULT_LIMIT }, signal),
  );
  const results = query ? (search.data ?? []) : [];
  const activeIndex = highlight.query === query ? Math.min(highlight.index, results.length - 1) : 0;
  const showPanel = open && text.trim() !== "";
  const pending = text.trim() !== query || search.loading;

  function choose(listing: Listing) {
    setOpen(false);
    setText("");
    router.push(stockHref(listing.exchange, listing.symbol));
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!results.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setHighlight({ query, index: (activeIndex + step + results.length) % results.length });
    } else if (event.key === "Enter" && showPanel) {
      event.preventDefault();
      const listing = results[activeIndex];
      if (listing) choose(listing);
    }
  }

  return (
    <div className="relative w-full max-w-md">
      <label htmlFor={`${listboxId}-input`} className="sr-only">
        Search stocks
      </label>
      <input
        id={`${listboxId}-input`}
        type="search"
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={
          showPanel && results.length ? `${listboxId}-${activeIndex}` : undefined
        }
        autoComplete="off"
        placeholder="Search stocks by symbol or company…"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none placeholder:text-zinc-400 focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:placeholder:text-zinc-500 dark:focus:border-zinc-500 dark:focus:ring-zinc-800"
      />
      {showPanel ? (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
          {search.error && !pending ? (
            <p className="px-3 py-2 text-sm text-red-600 dark:text-red-400">Search failed. Try again.</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-500 dark:text-zinc-400">
              {pending ? "Searching…" : "No matching stocks"}
            </p>
          ) : (
            <ul id={listboxId} role="listbox" aria-label="Stocks" className="max-h-80 overflow-y-auto py-1">
              {results.map((listing, index) => (
                <li
                  key={listing.listing_id}
                  id={`${listboxId}-${index}`}
                  role="option"
                  aria-selected={index === activeIndex}
                  // mousedown (not click) so the input's blur doesn't close the list first
                  onMouseDown={(event) => {
                    event.preventDefault();
                    choose(listing);
                  }}
                  onMouseEnter={() => setHighlight({ query, index })}
                  className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm ${
                    index === activeIndex ? "bg-zinc-100 dark:bg-zinc-800" : ""
                  }`}
                >
                  <span className="font-semibold">{listing.symbol}</span>
                  <ExchangeBadge exchange={listing.exchange} />
                  <span className="truncate text-zinc-500 dark:text-zinc-400">{listing.company_name}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
