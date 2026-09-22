// Minimal inline-SVG line chart, no charting library dependency. Shared by
// HostMetrics (disk usage trend) and Analiz (correlation metrics) so both
// pages plot time series the same way.
interface LineChartProps {
  values: number[];
  color?: string;
  height?: number;
  min?: number;
  max?: number;
}

export default function LineChart({ values, color = "#14213d", height = 120, min, max }: LineChartProps) {
  if (values.length === 0) {
    return <p className="empty-hint">Veri yok.</p>;
  }

  const lo = min ?? Math.min(0, ...values);
  const hi = max ?? Math.max(...values, lo + 1);
  const range = hi - lo || 1;
  const stepX = values.length > 1 ? 40 : 0;
  const width = Math.max(values.length * 40, 40);

  const toY = (v: number) => height - ((v - lo) / range) * (height - 20) - 10;

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        points={values.map((v, i) => `${i * stepX},${toY(v)}`).join(" ")}
      />
      {values.map((v, i) => (
        <circle key={i} cx={i * stepX} cy={toY(v)} r="3" fill={color} />
      ))}
    </svg>
  );
}
