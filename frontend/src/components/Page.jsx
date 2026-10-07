// Page frame and title shared by the screens. mx-auto centers the content on
// screens wider than 1320px, in line with the centered tabs above it.
export const PAGE = "mx-auto max-w-[1360px] px-4 sm:px-6 lg:px-8 py-8";

export function PageTitle({ children }) {
  return <h2 className="mb-2 text-[1.4rem] sm:text-[1.6rem] font-bold text-navy font-heading tracking-tight">{children}</h2>;
}

// Shown while /api/overview loads, or if the backend can't be reached.
export function PageStatus({ title, error }) {
  return (
    <section className={PAGE}>
      <PageTitle>{title}</PageTitle>
      {error ? (
        <div className="rounded-xl border border-red-200 bg-bad-bg p-4 text-[0.9rem] text-bad-text font-medium flex items-center gap-3" role="alert">
          <span className="size-2 rounded-full bg-red-500 animate-pulse" />
          <span>{error}</span>
        </div>
      ) : (
        <div className="flex items-center gap-3 py-12 text-muted">
          <div className="size-5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
          <p className="text-[0.92rem] font-medium">Loading operational data...</p>
        </div>
      )}
    </section>
  );
}
