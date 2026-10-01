import ForecastMap from "./ForecastMap.jsx";
import ForecastDetailsPanel from "./ForecastDetailsPanel.jsx";
import "./ForecastTrackSection.css";

export default function ForecastTrackSection({ storm, track }) {
  return (
    <section className="forecast-track" aria-labelledby="forecast-track-heading">
      <div className="forecast-track__heading">
        <h3 id="forecast-track-heading">Forecast Track</h3>
        <p className="forecast-track__subtitle">Projected storm path and forecast conditions</p>
      </div>

      <div className="forecast-track__grid">
        <ForecastMap track={track} />
        <ForecastDetailsPanel storm={storm} />
      </div>

      <p className="forecast-track__disclaimer">Prototype forecast data — not live NOAA/NHC data.</p>
    </section>
  );
}
