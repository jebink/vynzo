import { CHART_COLORS } from "@/features/price-charts/chart-theme";

const WIDTH = 120;
const HEIGHT = 32;
const PAD = 2;

/**
 * A small close-price line, green when the last close is at or above the first, red otherwise.
 * Plain SVG (no chart library) so hundreds can render in one list cheaply.
 */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) {
    return <span className="text-xs text-zinc-400 dark:text-zinc-500">Not enough data</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (WIDTH - PAD * 2) / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = PAD + i * step;
      const y = PAD + (1 - (v - min) / span) * (HEIGHT - PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  const color = up ? CHART_COLORS.up : CHART_COLORS.down;

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={WIDTH}
      height={HEIGHT}
      role="img"
      aria-label={label}
      className="block"
    >
      <polygon
        points={`${PAD},${HEIGHT - PAD} ${points} ${WIDTH - PAD},${HEIGHT - PAD}`}
        fill={color}
        fillOpacity={0.1}
      />
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
