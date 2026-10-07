import { useState, useRef, useEffect } from "react";

const NAV_ITEMS = [
  { id: "storm-overview", label: "Storm Overview" },
  { id: "resource-planner", label: "Resource Planner" },
];

export default function Navigation({
  activePage,
  onNavigate,
  items = NAV_ITEMS,
  onHome,
  title,
  agents = [],
  currentAgentId,
  onSelectAgent,
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const currentAgent = agents.find((a) => a.id === currentAgentId);

  return (
    <nav
      className="fixed inset-x-0 top-16 z-90 flex h-[50px] items-center justify-between border-b border-line glass-nav px-4 sm:px-8 shadow-xs"
      aria-label="Primary"
    >
      <div className="flex items-center gap-3">
        {onHome && (
          <button
            type="button"
            onClick={onHome}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1 text-[0.8rem] font-semibold text-muted shadow-xs transition-colors hover:border-accent hover:bg-sky-50 hover:text-accent"
          >
            <span aria-hidden="true">←</span>
            <span>All Scenarios</span>
          </button>
        )}

        {/* Quick Scenario Switcher Dropdown */}
        {agents.length > 0 && currentAgent && (
          <div className="relative" ref={dropdownRef}>
            <button
              type="button"
              onClick={() => setDropdownOpen((v) => !v)}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-sky-200/70 bg-sky-50/70 px-3 py-1 text-[0.84rem] font-bold text-navy transition-all hover:bg-sky-100/70 focus:outline-none"
              aria-expanded={dropdownOpen}
            >
              <span className="size-2 rounded-full bg-accent" />
              <span>{currentAgent.county ?? currentAgent.name}</span>
              <span className="text-[0.72rem] font-medium text-muted">
                {currentAgent.hazard === "hurricane" ? `(${currentAgent.replay ?? "Replay"})` : "(Winter)"}
              </span>
              <svg className={`size-3.5 text-muted transition-transform ${dropdownOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {dropdownOpen && (
              <div className="absolute left-0 top-full mt-1.5 w-72 rounded-xl border border-line glass-card p-1.5 shadow-xl z-100">
                <div className="px-2.5 py-1 text-[0.7rem] font-bold uppercase tracking-wider text-muted">Switch County Scenario</div>
                <div className="flex flex-col gap-0.5">
                  {agents.map((a) => {
                    const active = a.id === currentAgentId;
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => {
                          onSelectAgent?.(a.id);
                          setDropdownOpen(false);
                        }}
                        className={`flex w-full cursor-pointer items-center justify-between rounded-lg px-2.5 py-2 text-left text-[0.82rem] transition-colors ${
                          active
                            ? "bg-accent text-white font-semibold"
                            : "hover:bg-sky-50 text-ink"
                        }`}
                      >
                        <div className="flex flex-col">
                          <span className="font-semibold">{a.county ?? a.name}</span>
                          <span className={`text-[0.7rem] ${active ? "text-sky-100" : "text-muted"}`}>
                            {a.hazard === "hurricane" ? `Hurricane ${a.replay ?? ""} Replay` : "Winter Storm Grid"}
                          </span>
                        </div>
                        <span className={`rounded px-1.5 py-0.5 text-[0.65rem] font-bold uppercase ${
                          active ? "bg-white/20 text-white" : "bg-sky-100 text-accent-dark"
                        }`}>
                          {a.hazard}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {!currentAgent && title && (
          <span className="whitespace-nowrap font-heading text-[0.92rem] font-bold text-navy">{title}</span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1.5 overflow-x-auto py-1">
        {items.map((item) => {
          const isActive = activePage === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`inline-flex cursor-pointer items-center whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[0.84rem] font-semibold transition-all duration-150 ${
                isActive
                  ? "bg-sky-100/90 text-accent-dark ring-1 ring-sky-300/60 shadow-xs"
                  : "text-muted hover:bg-slate-100/70 hover:text-ink"
              }`}
              onClick={() => onNavigate(item.id)}
              aria-current={isActive ? "page" : undefined}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
