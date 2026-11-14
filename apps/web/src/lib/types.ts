// Response shapes of the market data and signals API (docs/api/market-data-and-signals.md).
// Timestamps are ISO-8601 UTC strings; daily/weekly/monthly bars sit at 00:00Z of the trading date.
// Fields the contract allows to be null (or that are null for some signal types) are typed `| null`.

export type Exchange = "NSE" | "BSE";

export const EXCHANGES: readonly Exchange[] = ["NSE", "BSE"];

export type Timeframe = "1d" | "1w" | "1mo" | "75m" | "15m" | "5m" | "1m";

// ---- Instruments ----

export interface Listing {
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  kind: string;
  company_name: string;
  isin: string | null;
  is_active: boolean;
}

export interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** `GET /v1/instruments/listings/{exchange}/{symbol}` */
export interface ListingDetail extends Listing {
  latest: Bar | null;
  previous_close: number | null;
}

/** One exchange listing of a symbol as the daily pipeline sees it. */
export interface ListingState {
  listing_id: number;
  /** Selected for the daily ingestion, indicators and signals. */
  is_active: boolean;
  provider_symbol: string | null;
  last_bar: string | null;
}

/** A symbol with its NSE and BSE listings (`null` where it has no listing on that exchange). */
export interface SelectionRow {
  symbol: string;
  company_name: string | null;
  isin: string | null;
  kind: string;
  nse: ListingState | null;
  bse: ListingState | null;
}

/** `GET /v1/instruments/selection` */
export interface SelectionPage {
  total: number;
  selected: Record<Exchange, number>;
  rows: SelectionRow[];
}

export type SelectionStatus = "all" | "selected" | "unselected";

// ---- Market data ----

/** `GET /v1/market-data/{exchange}/{symbol}/bars` */
export interface BarsResponse {
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  timeframe: Timeframe;
  bars: Bar[];
}

export interface IndicatorRow {
  ts: string;
  calc_version: string;
  rsi_14: number | null;
  ema_9: number | null;
  ema_21: number | null;
  ema_50: number | null;
  ema_200: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  atr_14: number | null;
  vwap: number | null;
  adx_14: number | null;
  plus_di_14: number | null;
  minus_di_14: number | null;
  rvol_20: number | null;
  donchian_high_20: number | null;
  donchian_low_20: number | null;
  donchian_high_55: number | null;
  bb_width: number | null;
  obv: number | null;
  ema200_slope_20: number | null;
  extension_atr: number | null;
  ret_126: number | null;
}

/** `GET /v1/market-data/{exchange}/{symbol}/indicators` */
export interface IndicatorsResponse {
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  rows: IndicatorRow[];
}

/** One ingested stock in `GET /v1/market-data/overview`. `closes` are daily, oldest first. */
export interface StockSnapshot {
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  kind: string;
  company_name: string | null;
  is_active: boolean;
  latest_ts: string | null;
  close: number | null;
  previous_close: number | null;
  change_pct: number | null;
  volume: number | null;
  closes: number[];
}

/** `GET /v1/market-data/overview` */
export interface OverviewResponse {
  as_of: string | null;
  points: number;
  stocks: StockSnapshot[];
}

// ---- Signals ----

/** `GET /v1/signals/types` item */
export interface SignalTypeSummary {
  signal_type: string;
  count: number;
  latest_as_of: string | null;
}

/** `GET /v1/signals` item */
export interface Signal {
  id: number;
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  company_name: string;
  signal_type: string;
  as_of: string;
  strength: number | null;
  price: number | null;
  volume: number | null;
  avg_volume: number | null;
  rationale: string | null;
  meta: Record<string, unknown> | null;
  calc_version: string;
}

/** `GET /v1/signals/swing` item (legacy swing signals). `signal` is BUY, SELL or e.g. HOLD. */
export interface SwingSignal {
  id: number;
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  as_of: string;
  signal: string;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  risk_reward: number | null;
  rationale: string | null;
  calc_version: string;
}

export const HIGH_VOLUME_BUY = "HIGH_VOLUME_BUY";

// ---- Opportunities ----

export type Horizon = "next_session" | "swing" | "long_term";
export type Direction = "BUY" | "SELL";
export type Confidence = "high" | "medium" | "low";

export interface FactorScore {
  /** trend | momentum | price_action | volume | volatility | relative_strength */
  group: string;
  /** -1 bearish .. +1 bullish */
  score: number;
  reason: string;
}

export interface MarketRegime {
  score: number;
  label: "bullish" | "neutral" | "bearish" | "unknown";
  notes: string[];
}

export interface Opportunity {
  id: number;
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  company_name: string | null;
  horizon: Horizon;
  as_of: string;
  direction: Direction;
  /** "actionable" passed every bar; "watch" is worth monitoring only. */
  status: "actionable" | "watch";
  score: number;
  confidence: Confidence;
  /** Last daily close. */
  price: number;
  entry_low: number;
  entry_high: number;
  stop_loss: number;
  targets: number[];
  risk_reward: number;
  holding_period: string;
  supports: number[];
  resistances: number[];
  reasons: string[];
  factors: FactorScore[];
  risks: string[];
  invalidation: string[];
  calc_version: string;
}

/** `GET /v1/opportunities` */
export interface OpportunitiesResponse {
  as_of: string | null;
  generated_at: string | null;
  regime: MarketRegime | null;
  data_note: string;
  horizons: Record<Horizon, Opportunity[]>;
}

export type OutcomeStatus = "target_hit" | "stopped" | "expired" | "not_triggered";

export interface ScoreBand {
  band: string;
  triggered: number;
  hit_rate: number | null;
  avg_return_pct: number | null;
}

export interface HorizonPerformance {
  picks: number;
  open: number;
  closed: Record<OutcomeStatus, number>;
  hit_rate: number | null;
  avg_return_pct: number | null;
  by_score: ScoreBand[];
}

export interface ClosedPick {
  id: number;
  symbol: string;
  exchange: Exchange;
  horizon: Horizon;
  direction: Direction;
  score: number;
  as_of: string;
  status: OutcomeStatus;
  return_pct: number | null;
  exit_at: string | null;
}

export type PickStatusFilter = "actionable" | "watch" | "all";

/** `GET /v1/opportunities/performance` */
export interface PerformanceResponse {
  status: PickStatusFilter;
  horizons: Record<Horizon, HorizonPerformance>;
  recent: ClosedPick[];
}
