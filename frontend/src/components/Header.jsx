import "./Header.css";
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
    <header className="app-header">
      <div className="app-header__identity">
        <img src={logo} alt="StormReady AI logo" className="app-header__logo" />
        <div className="app-header__brand">
          <span className="app-header__title">StormReady AI</span>
          <span className="app-header__subtitle">Storm Preparedness &amp; Response Intelligence</span>
        </div>
      </div>
      <button
        type="button"
        className={`ask-ai-trigger${askAIOpen ? " is-active" : ""}`}
        onClick={onAskAIClick}
        aria-expanded={askAIOpen}
      >
        <ChatIcon />
        Ask AI
      </button>
    </header>
  );
}
