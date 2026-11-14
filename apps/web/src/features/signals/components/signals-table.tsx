import Link from "next/link";
import { ExchangeBadge } from "@/components/exchange-badge";
import { formatDate, formatNumber, formatPrice, formatVolume } from "@/lib/format";
import { stockHref } from "@/lib/routes";
import { HIGH_VOLUME_BUY, type Signal } from "@/lib/types";
import { SignalTypeBadge } from "./signal-type-badge";

/** Volume signals are a multiple of average volume ("2.41×"); others show the raw score. */
function formatStrength(signal: Signal): string {
  if (signal.strength == null) return "—";
  return signal.signal_type === HIGH_VOLUME_BUY
    ? `${signal.strength.toFixed(2)}×`
    : formatNumber(signal.strength);
}

const TH = "px-3 py-2 font-medium whitespace-nowrap";
const TD = "px-3 py-2 align-top";

interface SignalsTableProps {
  signals: Signal[];
  /** Show the symbol and company columns (off on a single stock's page). */
  showInstrument?: boolean;
}

export function SignalsTable({ signals, showInstrument = true }: SignalsTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th scope="col" className={TH}>Date</th>
            {showInstrument ? (
              <>
                <th scope="col" className={TH}>Symbol</th>
                <th scope="col" className={TH}>Company</th>
              </>
            ) : null}
            <th scope="col" className={TH}>Type</th>
            <th scope="col" className={`${TH} text-right`}>Strength</th>
            <th scope="col" className={`${TH} text-right`}>Price</th>
            <th scope="col" className={`${TH} text-right`}>Volume vs avg</th>
            <th scope="col" className={TH}>Rationale</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
          {signals.map((signal) => (
            <tr key={signal.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-900/60">
              <td className={`${TD} whitespace-nowrap text-zinc-600 dark:text-zinc-400`}>
                {formatDate(signal.as_of)}
              </td>
              {showInstrument ? (
                <>
                  <td className={`${TD} whitespace-nowrap`}>
                    <span className="inline-flex items-center gap-1.5">
                      <Link
                        href={stockHref(signal.exchange, signal.symbol)}
                        className="font-semibold text-zinc-900 underline-offset-2 hover:underline dark:text-zinc-100"
                      >
                        {signal.symbol}
                      </Link>
                      <ExchangeBadge exchange={signal.exchange} />
                    </span>
                  </td>
                  <td className={`${TD} max-w-48 truncate text-zinc-700 dark:text-zinc-300`} title={signal.company_name}>
                    {signal.company_name}
                  </td>
                </>
              ) : null}
              <td className={TD}>
                <SignalTypeBadge type={signal.signal_type} />
              </td>
              <td className={`${TD} text-right tabular-nums`}>{formatStrength(signal)}</td>
              <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{formatPrice(signal.price)}</td>
              <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>
                {signal.volume == null ? (
                  "—"
                ) : (
                  <>
                    {formatVolume(signal.volume)}
                    {signal.avg_volume != null ? (
                      <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                        vs {formatVolume(signal.avg_volume)} avg
                      </span>
                    ) : null}
                  </>
                )}
              </td>
              <td
                className={`${TD} max-w-[14rem] truncate text-zinc-600 dark:text-zinc-400`}
                title={signal.rationale ?? undefined}
              >
                {signal.rationale ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
