import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import React from "react";

// auth.jsx wraps window.fetch once at import time, so route every call through a replaceable handler.
globalThis.__mockFetch = async () => new Response("{}", { status: 404 });
globalThis.fetch = (...args) => globalThis.__mockFetch(...args);

// jsdom has no canvas: replace the chart components with inert stubs.
vi.mock("react-chartjs-2", () => {
  const stub = (name) => (props) => React.createElement("canvas", { "data-testid": `chart-${name}`, "aria-label": `${name} chart`, "data-sets": props.data?.datasets?.length });
  return { Line: stub("line"), Bar: stub("bar"), Scatter: stub("scatter"), Doughnut: stub("doughnut") };
});

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.spyOn(console, "error").mockImplementation(() => {}); // expected error-boundary / failed-fetch logs
});

afterEach(() => {
  cleanup();
});
