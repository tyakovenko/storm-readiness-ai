import { useState, useEffect } from "react";
import logo from "../assets/storm-readiness-logo.png";

function SparklesIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
      <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
      <path d="M19 11h2m-1 -1v2" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}

export default function Header({ onAskAIClick, askAIOpen }) {
  const [isDark, setIsDark] = useState(() => {
    return document.documentElement.classList.contains("dark") ||
      window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [isDark]);

  return (
    <header className="fixed inset-x-0 top-0 z-100 flex h-16 items-center justify-between gap-4 glass-header border-b border-sky-900/50 px-5 sm:px-8 text-white">
      {/* Radiant bottom border */}
      <div className="absolute inset-x-0 bottom-0 h-[1.5px] bg-gradient-to-r from-transparent via-sky-400/70 via-teal-400/70 to-transparent" />

      <div className="flex min-w-0 items-center gap-3.5">
        <div className="relative flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10 p-1 ring-1 ring-white/20 backdrop-blur-sm">
          <img src={logo} alt="StormReady AI logo" className="block size-8 object-contain" />
        </div>
        <div className="flex flex-col leading-tight">
          <div className="flex items-center gap-2">
            <span className="font-heading text-[1.12rem] font-bold tracking-tight text-white">StormReady AI</span>
            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-0.5 text-[0.68rem] font-medium text-emerald-300 md:inline-flex">
              <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live Operations
            </span>
          </div>
          <span className="text-[0.72rem] font-medium text-sky-200/70 max-[520px]:hidden">
            Emergency Command &amp; Outage Forecasting
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Dark / Light Theme Toggle Button */}
        <button
          type="button"
          onClick={() => setIsDark((d) => !d)}
          title={isDark ? "Switch to Light Theme" : "Switch to Dark Theme"}
          className="inline-flex cursor-pointer items-center justify-center rounded-xl border border-white/15 bg-white/10 p-2 text-sky-200 transition-all hover:bg-white/20 hover:text-white"
          aria-label="Toggle Dark/Light theme"
        >
          {isDark ? <SunIcon /> : <MoonIcon />}
        </button>

        {/* Ask AI Pill Button */}
        <button
          type="button"
          className={`inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-xl px-4 py-2 text-[0.84rem] font-semibold transition-all duration-200 active:scale-95 ${
            askAIOpen
              ? "bg-sky-600 text-white shadow-inner ring-2 ring-sky-300/40"
              : "bg-gradient-to-r from-sky-500 to-teal-500 text-white shadow-md shadow-sky-900/30 hover:from-sky-400 hover:to-teal-400 hover:shadow-sky-500/25"
          }`}
          onClick={onAskAIClick}
          aria-expanded={askAIOpen}
        >
          <SparklesIcon />
          <span>Ask AI Assistant</span>
        </button>
      </div>
    </header>
  );
}
