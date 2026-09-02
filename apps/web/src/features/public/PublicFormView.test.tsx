import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicFormView } from "./PublicFormView";

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
});

describe("captación pública P14", () => {
  it("usa allowlists publicadas y permite enviar aunque la disponibilidad sea informativamente falsa", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url === "/api/v1/public/security-config/")
        return Promise.resolve(
          json({ antiabuse_provider: "deterministic", turnstile_site_key: "" }),
        );
      if (url.endsWith("/availability/")) return Promise.resolve(json({ available: false }));
      if (url.endsWith("/public/forms/form-locator/") && init?.method === "POST")
        return Promise.resolve(json({ event_request_id: "request-1", availability: false }, 201));
      if (url.endsWith("/public/forms/form-locator/"))
        return Promise.resolve(
          json({
            organization: "Eventos Claros",
            title: "Cuéntanos sobre tu evento",
            introduction: "Revisaremos tu solicitud.",
            event_types: [{ id: "event-type-1", revision: 3, label: "Boda" }],
            locations: [
              {
                venue_id: "venue-1",
                venue_revision: 2,
                venue_label: "Sede Centro",
                space_id: "space-1",
                space_revision: 4,
                space_label: "Salón principal",
              },
            ],
            durations_minutes: [120],
            timezone: "America/Guayaquil",
            consents: [],
            version: 1,
          }),
        );
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<PublicFormView locator="form-locator" />);
    expect(await screen.findByRole("heading", { name: "Cuéntanos sobre tu evento" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Ana Luz" } });
    fireEvent.change(screen.getByLabelText("Teléfono"), { target: { value: "0991234567" } });
    fireEvent.change(screen.getByLabelText("Invitados estimados"), { target: { value: "80" } });
    fireEvent.change(screen.getByLabelText("¿Qué necesitas?"), {
      target: { value: "Una celebración familiar" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Consultar disponibilidad/ }));
    expect(await screen.findByText(/intervalo aparece ocupado/)).toBeVisible();
    const submit = screen.getByRole("button", { name: "Enviar solicitud" });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    const form = submit.closest("form");
    if (!form) throw new Error("No se encontró el formulario público.");
    fireEvent.submit(form);
    expect(await screen.findByText(/horario requiere revisión/)).toBeVisible();

    await waitFor(() => {
      const submitted = fetchMock.mock.calls.find(
        ([input, init]) =>
          urlOf(input).endsWith("/public/forms/form-locator/") && init?.method === "POST",
      );
      expect(submitted).toBeDefined();
      const body = submitted?.[1]?.body;
      if (typeof body !== "string") throw new Error("No se envió JSON.");
      const payload: unknown = JSON.parse(body);
      expect(payload).toMatchObject({
        event_type_id: "event-type-1",
        space_id: "space-1",
        duration_minutes: 120,
        estimated_guests: 80,
      });
      if (
        !payload ||
        typeof payload !== "object" ||
        !("starts_at_local" in payload) ||
        typeof payload.starts_at_local !== "string"
      )
        throw new Error("No se envió la hora local publicada.");
      expect(payload.starts_at_local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
      expect(payload).not.toHaveProperty("ends_at");
    });
  });
});
