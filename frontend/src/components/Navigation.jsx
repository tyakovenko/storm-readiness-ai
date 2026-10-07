const NAV_ITEMS = [
  { id: "storm-overview", label: "Storm Overview" },
  { id: "resource-planner", label: "Resource Planner" },
];

// items/onHome/title are set by the multi-agent app (one page set per agent + "All agents");
// the single-agent app passes neither and gets the original two tabs.
export default function Navigation({ activePage, onNavigate, items = NAV_ITEMS, onHome, title }) {
  return (
    <nav
      className="fixed inset-x-0 top-14 z-90 flex h-[46px] items-center justify-center gap-8 overflow-x-auto border-b border-line bg-surface px-5 max-[560px]:gap-4"
      aria-label="Primary"
    >
      {onHome && (
        <button type="button" onClick={onHome}
          className="inline-flex h-full cursor-pointer items-center whitespace-nowrap bg-transparent text-[0.85rem] font-semibold text-accent hover:underline">
          ← Home
        </button>
      )}
      {title && <span className="whitespace-nowrap text-[0.9rem] font-bold text-navy">{title}</span>}
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`inline-flex h-full cursor-pointer items-center whitespace-nowrap border-b-2 bg-transparent px-0.5 text-[0.9rem] max-[560px]:text-[0.82rem] ${
            activePage === item.id
              ? "border-accent font-semibold text-accent"
              : "border-transparent font-medium text-muted hover:text-ink"
          }`}
          onClick={() => onNavigate(item.id)}
          aria-current={activePage === item.id ? "page" : undefined}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}
