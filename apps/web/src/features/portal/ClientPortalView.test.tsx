import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientPortalView } from "./ClientPortalView";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("portal seguro P14", () => {
  it("mantiene autenticación externa separada y muestra varios grants después del challenge", async () => {
    let authenticated = false;
    window.history.replaceState({}, "", "/portal?form=form-locator");
    const events = [
      {
        grant_id: "grant-1",
        event: { event_type: "Boda", starts_at: "2026-10-10T18:00:00Z", status: "new" },
      },
      {
        grant_id: "grant-2",
        event: { event_type: "Graduación", starts_at: "2026-11-10T18:00:00Z", status: "quoted" },
      },
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url === "/api/v1/public/security-config/")
        return Promise.resolve(
          json({ antiabuse_provider: "deterministic", turnstile_site_key: "" }),
        );
      if (url === "/api/v1/portal/auth/challenges/")
        return Promise.resolve(
          json({ challenge: "challenge.123456", message: "Instrucciones" }, 202),
        );
      if (url === "/api/v1/portal/auth/verify/") {
        authenticated = true;
        return Promise.resolve(json({ authenticated: true }));
      }
      if (url === "/api/v1/portal/session/")
        return Promise.resolve(
          authenticated ? json({ authenticated: true, events }) : json({ error: {} }, 401),
        );
      if (url.endsWith("/portal/events/grant-1/"))
        return Promise.resolve(json({ event: events[0]?.event, grant_id: "grant-1" }));
      if (url.endsWith("/portal/events/grant-1/documents/"))
        return Promise.resolve(json({ documents: [] }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ClientPortalView />);
    expect(await screen.findByRole("heading", { name: "Accede a tus eventos" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Correo"), {
      target: { value: "cliente@example.com" },
    });
    const requestButton = screen.getByRole("button", { name: "Solicitar acceso" });
    await waitFor(() => {
      expect(requestButton).toBeEnabled();
    });
    fireEvent.click(requestButton);
    expect(await screen.findByText("Instrucciones")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Código recibido"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verificar y entrar" }));

    expect(await screen.findByRole("button", { name: /Boda/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Graduación/ })).toBeVisible();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/portal/auth/verify/",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
