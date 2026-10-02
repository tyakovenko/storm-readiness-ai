// Shared look for the label/value rows in the side panels next to each map.
export const DETAIL_ITEM = "flex flex-col gap-0.5 border-b border-line pb-3.5 last:border-b-0 last:pb-0";
export const DETAIL_LABEL = "text-[0.68rem] font-bold uppercase tracking-[0.5px] text-muted";
export const DETAIL_VALUE = "text-[1.1rem] font-bold text-navy";
export const DETAIL_PANEL = "flex h-[420px] flex-col gap-3.5 rounded-md border border-line bg-surface p-4 max-[760px]:h-auto";

export default function ForecastDetailsPanel({ storm }) {
  return (
    <dl className={DETAIL_PANEL} aria-label="Forecast details">
      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Expected Landfall</dt>
        <dd className={DETAIL_VALUE}>{storm.landfallLocation}</dd>
        <dd className="text-[0.78rem] text-muted">~{storm.landfallHours} hours</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Rainfall</dt>
        <dd className={DETAIL_VALUE}>{storm.rainfallInches}</dd>
        <dd className="text-[0.78rem] text-muted">Forecast range</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Storm Movement</dt>
        <dd className={DETAIL_VALUE}>{storm.movementDirection}</dd>
        <dd className="text-[0.78rem] text-muted">{storm.movementSpeedMph} mph</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Max Wind</dt>
        <dd className={DETAIL_VALUE}>{storm.maxWindKt} kt</dd>
      </div>
    </dl>
  );
}
