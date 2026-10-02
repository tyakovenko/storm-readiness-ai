// Page frame and title shared by the screens. mx-auto centers the content on
// screens wider than 1320px, in line with the centered tabs above it.
export const PAGE = "mx-auto max-w-[1320px] px-8 py-7";

export function PageTitle({ children }) {
  return <h2 className="mb-2 text-[1.3rem] font-bold text-navy">{children}</h2>;
}

// Shown while /api/overview loads, or if the backend can't be reached.
export function PageStatus({ title, error }) {
  return (
    <section className={PAGE}>
      <PageTitle>{title}</PageTitle>
      {error ? (
        <p className="rounded bg-bad-bg px-3 py-2 text-[0.88rem] text-bad-text" role="alert">{error}</p>
      ) : (
        <p className="text-[0.88rem] text-muted">Loading…</p>
      )}
    </section>
  );
}
