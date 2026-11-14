// Display formatting for Indian equities (en-IN grouping, INR, UTC trading dates).

const priceFormat = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const compactFormat = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 2,
});

const dateFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const DASH = "—";

export function formatPrice(value: number | null | undefined): string {
  return value == null ? DASH : `₹${priceFormat.format(value)}`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null ? DASH : value.toFixed(digits);
}

/** Volumes in lakh/crore, e.g. 1.97Cr, 82L. */
export function formatVolume(value: number | null | undefined): string {
  return value == null ? DASH : compactFormat.format(value);
}

/** A bar or signal timestamp (00:00Z of the trading date) as e.g. "9 Nov 2026". */
export function formatDate(iso: string | null | undefined): string {
  return iso ? dateFormat.format(new Date(iso)) : DASH;
}

/** "+4.40" / "-1.20" */
export function formatSigned(value: number, digits = 2): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** "SOME_SIGNAL_TYPE" -> "Some signal type" */
export function humanizeSignalType(type: string): string {
  const words = type.toLowerCase().split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The trading date ("YYYY-MM-DD") of an ISO timestamp at 00:00Z. */
export function tradingDate(iso: string): string {
  return iso.slice(0, 10);
}
