import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { USERS, mockApi, renderAs, reply } from "./helpers.jsx";

// the form can only be submitted once the demo accounts have loaded and prefilled the email field
const ready = () => waitFor(() => expect(screen.getByLabelText(/work email/i)).toHaveValue(USERS.Manager.email));

const PERSONAS = { personas: ["Admin", "Manager", "Analyst"].map((r) => ({ role: r, name: USERS[r].name, email: USERS[r].email })) };

describe("route guard", () => {
  it("sends signed-out visitors to the login page", async () => {
    renderAs(null, "/risk", { "/api/auth/personas": PERSONAS });
    expect(await screen.findByRole("heading", { name: /sign in to your console/i })).toBeInTheDocument();
  });

  it("keeps a signed-in user on the page and shows who they are", async () => {
    renderAs("Manager", "/settings", { "/api/settings": { config: {}, user: USERS.Manager } });
    expect(await screen.findByText("Priya Sharma")).toBeInTheDocument();
    expect(screen.getAllByText("Manager").length).toBeGreaterThan(0);
  });

  it("signs the user out when the API answers 401 (expired or revoked session)", async () => {
    renderAs("Analyst", "/", {
      "/api/dashboard/summary": () => reply({ detail: "Session expired" }, 401),
      "/api/forecast/options": {},
      "/api/auth/personas": PERSONAS,
    });
    expect(await screen.findByRole("heading", { name: /sign in to your console/i })).toBeInTheDocument();
    expect(sessionStorage.getItem("diq_token")).toBeNull();
  });

  it("signs out on request and forgets the token", async () => {
    renderAs("Admin", "/", { "/api/dashboard/summary": { ready: false }, "/api/auth/personas": PERSONAS });
    await userEvent.click(await screen.findByRole("button", { name: /sign out/i }));
    expect(await screen.findByRole("heading", { name: /sign in to your console/i })).toBeInTheDocument();
    expect(sessionStorage.getItem("diq_token")).toBeNull();
  });
});

describe("login form", () => {
  it("offers the three demo roles and prefills the matching account", async () => {
    renderAs(null, "/login", { "/api/auth/personas": PERSONAS });
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent.replace("●", "").trim())).toEqual(["Admin", "Manager", "Analyst"]);
    expect(screen.getByLabelText(/work email/i)).toHaveValue(USERS.Manager.email);
    await userEvent.click(tabs[2]);
    expect(screen.getByLabelText(/work email/i)).toHaveValue(USERS.Analyst.email);
  });

  it("shows the server's message for bad credentials and clears the password", async () => {
    renderAs(null, "/login", { "/api/auth/personas": PERSONAS, "POST /api/auth/login": () => reply({ detail: "Invalid email or password" }, 401) });
    await ready();
    await userEvent.type(await screen.findByLabelText(/^password/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in to decision console/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(screen.getByLabelText(/^password/i)).toHaveValue("");
    expect(sessionStorage.getItem("diq_token")).toBeNull();
  });

  it("explains lockouts", async () => {
    renderAs(null, "/login", { "/api/auth/personas": PERSONAS, "POST /api/auth/login": () => reply({ detail: "Too many failed attempts. Try again in a few minutes." }, 429) });
    await ready();
    await userEvent.type(await screen.findByLabelText(/^password/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /sign in to decision console/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many failed attempts/i);
  });

  it("signs in, stores the token for the session only, and opens the dashboard", async () => {
    const { calls } = renderAs(null, "/login", {
      "/api/auth/personas": PERSONAS,
      "POST /api/auth/login": () => reply({ access_token: "tok-123", token_type: "bearer", expires_in: 28800, user: USERS.Manager }),
      "/api/auth/me": USERS.Manager,
      "/api/dashboard/summary": { ready: false },
    });
    await ready();
    await userEvent.type(await screen.findByLabelText(/^password/i), "a-valid-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in to decision console/i }));
    expect(await screen.findByText(/welcome to decisioniq/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("diq_token")).toBe("tok-123");
    expect(localStorage.getItem("diq_token")).toBeNull(); // not remembered unless the box is ticked
    const login = calls.find((c) => c.url === "/api/auth/login");
    expect(JSON.parse(login.init.body)).toEqual({ email: USERS.Manager.email, password: "a-valid-password", remember: false });
  });

  it("keeps the token in localStorage when 'remember this workstation' is ticked", async () => {
    renderAs(null, "/login", {
      "/api/auth/personas": PERSONAS, "POST /api/auth/login": () => reply({ access_token: "tok-remember", expires_in: 1, user: USERS.Manager }),
      "/api/dashboard/summary": { ready: false },
    });
    await ready();
    await userEvent.type(await screen.findByLabelText(/^password/i), "a-valid-password");
    await userEvent.click(screen.getByLabelText(/remember this workstation/i));
    await userEvent.click(screen.getByRole("button", { name: /sign in to decision console/i }));
    await waitFor(() => expect(localStorage.getItem("diq_token")).toBe("tok-remember"));
  });

  it("disables the SSO buttons that are not configured", async () => {
    renderAs(null, "/login", { "/api/auth/personas": { personas: [] } });
    expect(await screen.findByRole("button", { name: /google workspace/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /microsoft entra id/i })).toBeDisabled();
    expect(screen.queryAllByRole("tab")).toHaveLength(0); // no role tabs when demo mode is off
  });
});

describe("authenticated requests", () => {
  it("sends the bearer token on API calls and shows a toast for permission errors", async () => {
    const { calls } = renderAs("Analyst", "/", {
      "/api/dashboard/summary": { ready: false },
      "/api/forbidden-thing": () => reply({ detail: "Your role (Analyst) is not permitted to: Approve actions" }, 403),
    });
    await screen.findByText(/welcome to decisioniq/i);
    await fetch("/api/forbidden-thing");
    expect(await screen.findByText(/not permitted to: approve actions/i)).toBeInTheDocument();
    const withAuth = calls.filter((c) => c.url.startsWith("/api/dashboard/summary"))[0];
    expect(withAuth.init.headers.Authorization).toBe("Bearer test-token-Analyst");
  });

  it("shows a toast for server errors and unreachable servers", async () => {
    renderAs("Admin", "/", { "/api/dashboard/summary": { ready: false }, "/api/boom": () => reply({ detail: "x" }, 500) });
    await screen.findByText(/welcome to decisioniq/i);
    await fetch("/api/boom");
    expect(await screen.findByText(/server hit an error \(500\)/i)).toBeInTheDocument();
    globalThis.__mockFetch = () => Promise.reject(new TypeError("network down"));
    await expect(fetch("/api/anything")).rejects.toThrow();
    expect(await screen.findByText(/cannot reach the server/i)).toBeInTheDocument();
  });
});
