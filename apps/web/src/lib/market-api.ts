// Typed fetchers for the market data and signals API (docs/api/market-data-and-signals.md).
import { apiGet, apiPut } from "@/lib/api";
import type {
  BarsResponse,
  Exchange,
  IndicatorsResponse,
  Listing,
  ListingDetail,
  OpportunitiesResponse,
  OverviewResponse,
  PerformanceResponse,
  PickStatusFilter,
  SelectionPage,
  SelectionRow,
  SelectionStatus,
  Signal,
  SignalTypeSummary,
  SwingSignal,
  Timeframe,
} from "@/lib/types";

type Query = Record<string, string | number | boolean | null | undefined>;

/** Builds `?a=1&b=2`, skipping null/undefined/empty values. */
function query(params: Query): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function stockPath(exchange: Exchange, symbol: string): string {
  return `${encodeURIComponent(exchange)}/${encodeURIComponent(symbol)}`;
}

const opts = (signal?: AbortSignal): RequestInit => ({ signal });

// ---- Instruments ----

export function searchListings(
  params: { q?: string; exchange?: Exchange; active?: boolean; limit?: number },
  signal?: AbortSignal,
): Promise<Listing[]> {
  return apiGet(`/v1/instruments/listings${query(params)}`, opts(signal));
}

/** Rejects with an `ApiError` whose status is 404 for an unknown exchange/symbol. */
export function getListing(
  exchange: Exchange,
  symbol: string,
  signal?: AbortSignal,
): Promise<ListingDetail> {
  return apiGet(`/v1/instruments/listings/${stockPath(exchange, symbol)}`, opts(signal));
}

// ---- Ingestion selection (admin) ----

export function getSelection(
  params: { q?: string; status?: SelectionStatus; offset?: number; limit?: number },
  signal?: AbortSignal,
): Promise<SelectionPage> {
  return apiGet(`/v1/instruments/selection${query(params)}`, opts(signal));
}

/** Selects or deselects one exchange listing of `symbol` for the daily pipeline. */
export function setSelection(exchange: Exchange, symbol: string, selected: boolean): Promise<SelectionRow> {
  return apiPut(`/v1/instruments/selection/${stockPath(exchange, symbol)}`, { selected });
}

// ---- Market data ----

export function getBars(
  exchange: Exchange,
  symbol: string,
  params: { timeframe?: Timeframe; limit?: number; end?: string },
  signal?: AbortSignal,
): Promise<BarsResponse> {
  return apiGet(`/v1/market-data/${stockPath(exchange, symbol)}/bars${query(params)}`, opts(signal));
}

export function getIndicators(
  exchange: Exchange,
  symbol: string,
  params: { limit?: number; end?: string },
  signal?: AbortSignal,
): Promise<IndicatorsResponse> {
  return apiGet(
    `/v1/market-data/${stockPath(exchange, symbol)}/indicators${query(params)}`,
    opts(signal),
  );
}

/** Every ingested stock with its latest close, change and last `points` daily closes. */
export function getOverview(
  params: { exchange?: Exchange; points?: number },
  signal?: AbortSignal,
): Promise<OverviewResponse> {
  return apiGet(`/v1/market-data/overview${query(params)}`, opts(signal));
}

// ---- Signals ----

export function getSignalTypes(signal?: AbortSignal): Promise<SignalTypeSummary[]> {
  return apiGet(`/v1/signals/types`, opts(signal));
}

export function getSignals(
  params: {
    signal_type?: string;
    exchange?: Exchange;
    symbol?: string;
    since?: string;
    limit?: number;
  },
  signal?: AbortSignal,
): Promise<Signal[]> {
  return apiGet(`/v1/signals${query(params)}`, opts(signal));
}

export function getSwingSignals(
  params: { exchange?: Exchange; symbol?: string; limit?: number },
  signal?: AbortSignal,
): Promise<SwingSignal[]> {
  return apiGet(`/v1/signals/swing${query(params)}`, opts(signal));
}

// ---- Opportunities ----

/** The newest session's ranked picks per horizon. */
export function getOpportunities(signal?: AbortSignal): Promise<OpportunitiesResponse> {
  return apiGet(`/v1/opportunities`, opts(signal));
}

/** Track record of actionable (default), monitor-only ("watch") or all picks. */
export function getOpportunityPerformance(
  status: PickStatusFilter = "actionable",
  signal?: AbortSignal,
): Promise<PerformanceResponse> {
  return apiGet(`/v1/opportunities/performance${query({ status })}`, opts(signal));
}
