import MetricItem from "./MetricItem.jsx";
import { getStormSeverityColor } from "../../utils/stormSeverity.js";

export default function StormMetrics({ storm }) {
  return (
    <dl
      className="flex overflow-hidden rounded-md border border-line bg-surface max-[760px]:flex-wrap"
      aria-label="Primary storm metrics"
    >
      <MetricItem
        label="Category"
        value={storm.category}
        sublabel={storm.classification}
        valueColor={getStormSeverityColor(storm.category)}
      />
      <MetricItem label="Max Wind" value={`${storm.maxWindKt} kt`} sublabel="Sustained winds" />
      <MetricItem label="Landfall" value={`~${storm.landfallHours} hrs`} sublabel="Estimated" />
      <MetricItem label="Counties at Risk" value={storm.countiesAtRisk} sublabel="Predicted impact area" />
    </dl>
  );
}
