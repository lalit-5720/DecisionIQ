import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorBoundary, ErrorBox, PageSkeleton, Skeleton } from "../components/ui.jsx";

function Bomb({ explode }) {
  if (explode) throw new Error("chart exploded");
  return <p>all good</p>;
}

describe("ErrorBoundary", () => {
  it("contains a crashing page instead of blanking the app, and can recover", async () => {
    function Host() {
      const [explode, setExplode] = useState(true);
      return (
        <div>
          <nav>sidebar still here</nav>
          <ErrorBoundary key={String(explode)}>
            <Bomb explode={explode} />
          </ErrorBoundary>
          <button onClick={() => setExplode(false)}>fix it</button>
        </div>
      );
    }
    render(<Host />);
    expect(screen.getByRole("alert")).toHaveTextContent(/this page failed to render/i);
    expect(screen.getByRole("alert")).toHaveTextContent("chart exploded");
    expect(screen.getByText("sidebar still here")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /fix it/i }));
    expect(screen.getByText("all good")).toBeInTheDocument();
  });

  it("'Try again' re-renders the children", async () => {
    let explode = true;
    const Flaky = () => {
      if (explode) throw new Error("boom");
      return <p>recovered</p>;
    };
    render(<ErrorBoundary><Flaky /></ErrorBoundary>);
    explode = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });
});

describe("state components", () => {
  it("ErrorBox shows the message and a working retry", async () => {
    const retry = vi.fn();
    render(<ErrorBox message="Backend unreachable" onRetry={retry} title="Could not load" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("ErrorBox without a retry handler has no button", () => {
    render(<ErrorBox message="x" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("EmptyState renders its guidance and actions", () => {
    render(<EmptyState title="No data yet" hint="Upload a CSV"><button>Upload</button></EmptyState>);
    expect(screen.getByRole("heading", { name: "No data yet" })).toBeInTheDocument();
    expect(screen.getByText("Upload a CSV")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("skeletons are announced as loading", () => {
    render(<><Skeleton /><PageSkeleton rows={1} /></>);
    expect(screen.getAllByRole("status", { name: /loading/i }).length).toBeGreaterThan(4);
  });
});
