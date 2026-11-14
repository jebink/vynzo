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
