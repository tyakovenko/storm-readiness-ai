import "./ForecastDetailsPanel.css";

export default function ForecastDetailsPanel({ storm }) {
  return (
    <dl className="forecast-details" aria-label="Forecast details">
      <div className="forecast-details__item">
        <dt className="forecast-details__label">Expected Landfall</dt>
        <dd className="forecast-details__value">{storm.landfallLocation}</dd>
        <dd className="forecast-details__sublabel">~{storm.landfallHours} hours</dd>
      </div>

      <div className="forecast-details__item">
        <dt className="forecast-details__label">Rainfall</dt>
        <dd className="forecast-details__value">{storm.rainfallInches}</dd>
        <dd className="forecast-details__sublabel">Forecast range</dd>
      </div>

      <div className="forecast-details__item">
        <dt className="forecast-details__label">Storm Movement</dt>
        <dd className="forecast-details__value">{storm.movementDirection}</dd>
        <dd className="forecast-details__sublabel">{storm.movementSpeedMph} mph</dd>
      </div>

      <div className="forecast-details__item">
        <dt className="forecast-details__label">Max Wind</dt>
        <dd className="forecast-details__value">{storm.maxWindKt} kt</dd>
      </div>
    </dl>
  );
}
