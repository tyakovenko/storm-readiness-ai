import logo from "../assets/storm-readiness-logo.png";

function ChatIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v6A1.5 1.5 0 0 1 12.5 11H6.8l-2.9 2.3a.5.5 0 0 1-.8-.4V11A1.5 1.5 0 0 1 2 9.5v-6Z"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
      />
    </svg>
  );
}

export default function Header({ onAskAIClick, askAIOpen }) {
  return (
    <header className="fixed inset-x-0 top-0 z-100 flex h-14 items-center justify-between gap-4 bg-navy px-5 text-white max-[520px]:px-3.5">
      <div className="flex min-w-0 items-center gap-3">
        <img src={logo} alt="StormReady AI logo" className="block size-12 shrink-0 rounded-md bg-white object-contain p-1" />
        <div className="flex flex-col leading-[1.25]">
          <span className="text-[1.05rem] font-semibold tracking-[0.2px]">StormReady AI</span>
          <span className="text-[0.72rem] font-normal text-white/65 max-[520px]:hidden">Storm Preparedness &amp; Response Intelligence</span>
        </div>
      </div>
      <button
        type="button"
        className={`inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded border px-3.5 py-[7px] text-[0.85rem] font-semibold text-white hover:bg-accent-dark ${
          askAIOpen ? "border-white/40 bg-accent-dark" : "border-transparent bg-accent"
        }`}
        onClick={onAskAIClick}
        aria-expanded={askAIOpen}
      >
        <ChatIcon />
        Ask AI
      </button>
    </header>
  );
}
