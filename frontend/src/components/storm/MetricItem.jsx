// One cell of a metrics strip (StormMetrics, ResourceSummary). Cells sit side by
// side, wrap to two columns under 760px and stack under 480px.
export default function MetricItem({ label, value, sublabel, valueColor }) {
  return (
    <div className="flex min-w-[150px] flex-[1_1_0] flex-col gap-1 border-r border-line px-5 py-3.5 last:border-r-0 max-[760px]:flex-[1_1_50%] max-[760px]:border-b max-[760px]:even:border-r-0 max-[760px]:[&:nth-last-child(-n+2)]:border-b-0 max-[480px]:flex-[1_1_100%] max-[480px]:border-r-0 max-[480px]:last:border-b-0">
      <dt className="text-[0.7rem] font-bold uppercase tracking-[0.5px] text-muted">{label}</dt>
      <dd className="text-2xl font-bold leading-[1.2] text-navy" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </dd>
      <dd className="text-[0.78rem] text-muted">{sublabel}</dd>
    </div>
  );
}
