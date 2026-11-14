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
export type CapCategory = "large" | "mid" | "small";

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
  sector: string | null;
  /** INR: shares outstanding × last close; null until the profiles job has run. */
  market_cap: number | null;
  cap_category: CapCategory | null;
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

/** A named swing strategy that agrees with a pick (see `STRATEGIES` in features/opportunities). */
export interface SetupTag {
  key: string;
  /** e.g. which crossover ("9/21", "50/200") or chart pattern ("flag", "double_bottom"). */
  variant: string;
  reason: string;
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
  /** Swing only; empty for other horizons and for picks made before model opp-1.5.0. */
  setups: SetupTag[];
  calc_version: string;
  sector: string | null;
  /** INR: shares outstanding × price; null until the profiles job has run. */
  market_cap: number | null;
  cap_category: CapCategory | null;
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

// ---- Stock page strategies and backtest ----

/** A named swing setup detected at the last close, in either direction. */
export interface StockSetup {
  key: string;
  variant: string;
  direction: Direction;
  reason: string;
  stop: number;
}

export interface StockPick {
  direction: Direction;
  status: "actionable" | "watch";
  score: number;
  confidence: Confidence;
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
  setups: StockSetup[];
}

/** The first gate a horizon failed; factors are empty when it failed before scoring. */
export interface Rejection {
  reason: string;
  factors: FactorScore[];
  score: number | null;
}

/** `GET /v1/opportunities/stocks/{exchange}/{symbol}` */
export interface StockStrategiesResponse {
  exchange: Exchange;
  symbol: string;
  as_of: string | null;
  regime: MarketRegime | null;
  horizons: Record<Horizon, { pick: StockPick | null; rejection: Rejection | null }>;
  setups: StockSetup[];
}

export interface BacktestTrade {
  /** "<horizon>:<strategy key>", e.g. "swing:breakout" or "long_term:factor_confluence". */
  strategy: string;
  as_of: string;
  direction: Direction;
  outcome: "target_hit" | "stopped" | "expired" | "not_triggered" | "open";
  entry_at: string | null;
  entry_price: number | null;
  exit_at: string | null;
  exit_price: number | null;
  return_pct: number | null;
  sessions_held: number | null;
  excess_vs_nifty_pct: number | null;
  /** Measured causes of a losing entered trade; empty otherwise (and absent on old cached runs). */
  loss_reasons?: LossReason[];
}

export interface LossReason {
  code: string;
  text: string;
}

export interface BacktestSummary {
  picks: number;
  open: number;
  entered: number;
  hit_rate: number | null;
  win_rate: number | null;
  avg_return_pct: number | null;
  median_return_pct: number | null;
  excess_vs_nifty_pct: number | null;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  avg_sessions_held: number | null;
  equity: { t: string; equity: number }[];
}

/** One NDJSON line of `GET /v1/opportunities/stocks/{exchange}/{symbol}/backtest`. */
export type BacktestEvent = { cached?: boolean } & (
  | { type: "start"; sessions: number; first: string | null; last: string | null }
  | { type: "progress"; done: number; through: string; trades: BacktestTrade[] }
  | { type: "done"; summary: Record<string, BacktestSummary> }
);

/** One row of `GET /v1/fundamentals/events` (upcoming results and ex-dividend dates). */
export interface CorporateEvent {
  exchange: Exchange;
  symbol: string;
  company_name: string | null;
  event_type: "results" | "ex_dividend";
  event_date: string; // YYYY-MM-DD
  details: { amount?: number; eps_estimate?: number; window_end?: string };
  source: string;
}

/** `GET /v1/market-data/{exchange}/{symbol}/forecast`: latest close forecast per model. */
export interface ModelForecast {
  model: string;
  as_of: string; // date of the last bar the forecast starts from
  horizon: number;
  /** What the model would have predicted over past sessions (forecasts made every `horizon`). */
  history: { date: string; close: number }[];
  /** Walk-forward score: mean absolute % error and share of 20-day directions called right. */
  metrics: { mape: number | null; hit_rate: number | null; n: number | null };
}

export interface ForecastResponse {
  listing_id: number;
  exchange: Exchange;
  symbol: string;
  best_model: string | null;
  forecasts: ModelForecast[];
}

// ---- Need to focus (dashboard) ----

export interface FocusPart {
  points: number;
  max: number;
  reason: string;
}

/** `GET /v1/focus`: the one stock that most needs attention now. */
export interface FocusResponse {
  as_of: string | null;
  stock: {
    listing_id: number;
    exchange: Exchange;
    symbol: string;
    company_name: string | null;
    sector: string | null;
    /** 0-100: news (45) + market move (35) + upcoming event (20). */
    score: number;
    grade: "A" | "B" | "C" | "D";
    parts: Record<"news" | "market" | "event", FocusPart>;
    news: {
      label: string | null;
      sentiment: number | null;
      confidence: number | null;
      summary: string | null;
      headline_count: number;
      headlines: { title: string; url: string; source: string; publisher: string | null; published: string | null }[];
    } | null;
    performance: {
      close: number | null;
      change_1d_pct: number | null;
      change_5d_pct: number | null;
      change_20d_pct: number | null;
      move_sigma: number | null;
      rvol: number | null;
    };
    event: { type: string; date: string; days_away: number; details: Record<string, unknown> } | null;
  } | null;
}

// ---- Company overview (stock page) ----

/** `GET /v1/fundamentals/{exchange}/{symbol}`. Fractions for growth/margins/ROE/holdings; INR amounts. */
export interface CompanyOverview {
  exchange: Exchange;
  symbol: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  price: number | null;
  price_as_of: string | null;
  market_cap: number | null;
  fundamentals_as_of: string | null;
  metrics: {
    trailing_pe: number | null;
    forward_pe: number | null;
    price_to_book: number | null;
    revenue_ttm: number | null;
    revenue_growth: number | null;
    net_income_ttm: number | null;
    profit_margin: number | null;
    return_on_equity: number | null;
    total_debt: number | null;
    total_cash: number | null;
    debt_to_equity: number | null;
    current_ratio: number | null;
    free_cash_flow: number | null;
  };
  industry_pe: { median: number | null; peers: number; basis: "industry" | "sector" | null; group: string | null };
  ownership: { insider_pct: number | null; institutional_pct: number | null };
  dividends: { ttm_per_share: number | null; yield_pct: number | null; payouts: { ex_date: string; amount: number }[] };
  annual: { fiscal_year_end: string; revenue: number | null; net_income: number | null; total_debt: number | null }[];
  /** Highest fiscal-year-end debt minus the latest (balance sheet); 0 when the latest is the peak. */
  debt_cleared: {
    peak: number;
    peak_year_end: string;
    latest: number;
    latest_year_end: string;
    cleared: number;
    cleared_pct: number;
  } | null;
  orders: {
    reported_on: string;
    counterparty: string | null;
    description: string;
    value_inr: number | null;
    source_url: string;
    headline: string;
  }[];
}
