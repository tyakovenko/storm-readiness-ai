import "./Navigation.css";

const NAV_ITEMS = [
  { id: "storm-overview", label: "Storm Overview" },
  { id: "risk-map", label: "Risk Map" },
  { id: "resource-planner", label: "Resource Planner" },
];

export default function Navigation({ activePage, onNavigate }) {
  return (
    <nav className="sub-nav" aria-label="Primary">
      {NAV_ITEMS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`sub-nav__item${activePage === item.id ? " is-active" : ""}`}
          onClick={() => onNavigate(item.id)}
          aria-current={activePage === item.id ? "page" : undefined}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}
