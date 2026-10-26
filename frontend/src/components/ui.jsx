import { Component } from "react";

export function Skeleton({ className = "h-24" }) {
  return <div role="status" aria-label="Loading" className={`animate-pulse rounded-xl border border-line bg-card/60 ${className}`} />;
}

export function PageSkeleton({ rows = 3 }) {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-10 w-72" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-64" />)}
    </div>
  );
}

export function ErrorBox({ message, onRetry, title = "Something went wrong" }) {
  return (
    <div role="alert" className="rounded-xl border border-risk/40 bg-risk/10 p-4 text-sm">
      <div className="font-semibold text-risk">{title}</div>
      <p className="mt-1 text-muted">{message}</p>
      {onRetry && <button onClick={onRetry} className="mt-3 rounded-lg border border-risk/40 px-3 py-1.5 text-xs font-semibold text-risk hover:bg-risk/10">Try again</button>}
    </div>
  );
}

export function EmptyState({ icon = "📭", title, hint, children }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-card/40 p-8 text-center">
      <div className="text-3xl" aria-hidden>{icon}</div>
      <h3 className="mt-2 text-lg font-semibold">{title}</h3>
      {hint && <p className="mx-auto mt-1 max-w-md text-sm text-muted">{hint}</p>}
      {children && <div className="mt-4 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}

// A rendering crash in one page (for example a chart) must not blank the whole app.
export class ErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("Page crashed:", error, info?.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <ErrorBox title="This page failed to render" message={`${this.state.error.message || this.state.error}. The rest of the app is unaffected.`}
        onRetry={() => this.setState({ error: null })} />
    );
  }
}
