// Minimal inline-SVG line chart, no charting library dependency. Shared by
// HostMetrics (disk usage trend) and Analiz (correlation metrics) so both
// pages plot time series the same way.
interface LineChartProps {
  values: number[];
  timestamps?: number[]; // epoch ms, parallel to values -- renders x-axis tick labels when given
  color?: string;
  height?: number;
  min?: number;
  max?: number;
}

function formatTick(ms: number, spanMs: number): string {
  const d = new Date(ms);
  // Sub-3-day span: enough resolution to show the hour. Longer spans would
  // just repeat the same date under every tick, so show date+time only when
  // it's actually distinguishable.
  if (spanMs <= 3 * 24 * 60 * 60 * 1000) {
    return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" });
}

export default function LineChart({ values, timestamps, color = "#14213d", height = 120, min, max }: LineChartProps) {
  if (values.length === 0) {
    return <p className="empty-hint">Veri yok.</p>;
  }

  const lo = min ?? Math.min(0, ...values);
  const hi = max ?? Math.max(...values, lo + 1);
  const range = hi - lo || 1;
  const stepX = values.length > 1 ? 40 : 0;
  const width = Math.max(values.length * 40, 40);
  // Too many points make individual markers overlap into a smear rather
  // than help readability -- keep the line, drop the dots past this count.
  const showDots = values.length <= 60;

  const toY = (v: number) => height - ((v - lo) / range) * (height - 20) - 10;

  const ticks: { x: number; label: string }[] = [];
  if (timestamps && timestamps.length === values.length && values.length > 1) {
    const tickCount = Math.min(5, values.length);
    const spanMs = timestamps[timestamps.length - 1] - timestamps[0];
    for (let t = 0; t < tickCount; t++) {
      const i = Math.round((t / (tickCount - 1)) * (values.length - 1));
      ticks.push({ x: i * stepX, label: formatTick(timestamps[i], spanMs) });
    }
  }

  return (
    <div>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="2"
          points={values.map((v, i) => `${i * stepX},${toY(v)}`).join(" ")}
        />
        {showDots &&
          values.map((v, i) => <circle key={i} cx={i * stepX} cy={toY(v)} r="3" fill={color} />)}
      </svg>
      {ticks.length > 0 && (
        <div className="chart-ticks">
          {ticks.map((t, i) => (
            <span key={i}>{t.label}</span>
          ))}
        </div>
      )}
    </div>
  );
}
