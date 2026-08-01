import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("flujo comercial de Claridez", () => {
  it("muestra ingreso y recuperación cuando no hay sesión", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(json({ error: { code: "unauthenticated" } }, 401)),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Ingresa a tu organización" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Olvidé mi contraseña" }));
    expect(screen.getByRole("heading", { name: "Recupera tu acceso" })).toBeVisible();
    expect(screen.getByLabelText("Correo electrónico")).toBeRequired();
  });

  it("carga la organización, agenda y estado vacío real", async () => {
    const organization = { id: "org-1", name: "Salón Horizonte", slug: "horizonte" };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url === "/api/v1/auth/me/")
        return Promise.resolve(
          json({ user: { id: "user-1", email: "owner@example.test", display_name: "Ana" } }),
        );
      if (url === "/api/v1/organizations/")
        return Promise.resolve(json({ organizations: [organization] }));
      if (url === "/api/v1/organizations/context/") return Promise.resolve(json({ organization }));
      if (url.endsWith("/commercial/capabilities/"))
        return Promise.resolve(
          json({ capabilities: ["sales:read", "sales:manage", "availability:read"] }),
        );
      if (url.endsWith("/settings/"))
        return Promise.resolve(json({ settings: { timezone: "America/Guayaquil" } }));
      if (url.includes("/availability/?"))
        return Promise.resolve(
          json({
            from: "2026-07-31T05:00:00Z",
            to: "2026-08-07T05:00:00Z",
            available: true,
            blocks: [],
          }),
        );
      if (url.endsWith("/event-requests/")) return Promise.resolve(json({ event_requests: [] }));
      if (url.endsWith("/people/")) return Promise.resolve(json({ people: [] }));
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Agenda y disponibilidad" })).toBeVisible();
    expect(await screen.findByText("Semana disponible")).toBeVisible();
    expect(screen.getByText("Horarios bloqueados en America/Guayaquil.")).toBeVisible();

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Navegación principal" })).getByRole("button", {
        name: /Solicitudes/,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Solicitudes" })).toBeVisible();
    expect(await screen.findByText("Aún no hay solicitudes")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Nueva solicitud" }));
    expect(await screen.findByRole("heading", { name: "Registra una solicitud" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Registrar nueva" }));
    expect(screen.getByLabelText("Teléfono ecuatoriano")).toBeRequired();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/availability/?"),
        expect.objectContaining({ credentials: "same-origin" }),
      );
    });
  });

  it("confirma y cancela una reserva conservando la constancia externa", async () => {
    const organization = { id: "org-1", name: "Salón Horizonte", slug: "horizonte" };
    let reservationStatus: "provisional" | "confirmed" | "cancelled" = "provisional";
    const request = () => ({
      id: "request-1",
      person: {
        id: "person-1",
        full_name: "María Torres",
        phone_e164: "+593991234567",
        commercial_type: reservationStatus === "provisional" ? "lead" : "client",
        revision: 1,
      },
      event_type: "Boda",
      starts_at: "2026-09-12T20:00:00Z",
      ends_at: "2026-09-13T02:00:00Z",
      event_timezone: "America/Guayaquil",
      estimated_guests: 120,
      general_need: "Salón y mobiliario",
      notes: "",
      origin: "whatsapp",
      status: reservationStatus === "provisional" ? "accepted" : reservationStatus,
      revision: 1,
      quotation_id: "quotation-1",
      reservation: null,
    });
    const reservation = () => ({
      id: "reservation-1",
      status: reservationStatus,
      starts_at: "2026-09-12T20:00:00Z",
      ends_at: "2026-09-13T02:00:00Z",
      event_timezone: "America/Guayaquil",
      hold_expires_at: "2026-08-02T20:00:00Z",
      confirmation_kind: reservationStatus === "provisional" ? null : "external_deposit",
      recognized_deposit_amount: reservationStatus === "provisional" ? null : "100.00",
      deposit_reported_at: reservationStatus === "provisional" ? null : "2026-07-31T18:00:00Z",
      deposit_reference: reservationStatus === "provisional" ? null : "Transferencia reportada",
      confirmed_at: reservationStatus === "provisional" ? null : "2026-07-31T18:05:00Z",
      waiver_reason: null,
      waiver_authorized_at: null,
      cancelled_at: reservationStatus === "cancelled" ? "2026-07-31T19:00:00Z" : null,
      cancellation_reason: reservationStatus === "cancelled" ? "Cambio de planes" : null,
    });
    const quotation = {
      id: "quotation-1",
      event_request_id: "request-1",
      visible_number: "COT-2026-000001",
      versions: [
        {
          id: "version-1",
          version: 1,
          revision: 2,
          status: "Aceptada",
          stored_status: "accepted",
          valid_until: "2026-08-04T18:00:00Z",
          currency: "USD",
          subtotal: "500.00",
          discount_total: "0.00",
          total: "500.00",
          notes: "",
          lines: [],
          reservation_id: "reservation-1",
        },
      ],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url === "/api/v1/auth/me/")
        return Promise.resolve(
          json({ user: { id: "user-1", email: "owner@example.test", display_name: "Ana" } }),
        );
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf-test" }));
      if (url === "/api/v1/organizations/")
        return Promise.resolve(json({ organizations: [organization] }));
      if (url === "/api/v1/organizations/context/") return Promise.resolve(json({ organization }));
      if (url.endsWith("/commercial/capabilities/"))
        return Promise.resolve(
          json({
            capabilities: [
              "person:read",
              "sales:read",
              "sales:manage",
              "availability:read",
              "reservation:confirm",
              "reservation:cancel",
              "reservation:waive_deposit",
            ],
          }),
        );
      if (url.endsWith("/settings/"))
        return Promise.resolve(json({ settings: { timezone: "America/Guayaquil" } }));
      if (url.includes("/availability/?"))
        return Promise.resolve(
          json({ from: "2026-07-31T05:00:00Z", to: "2026-08-07T05:00:00Z", blocks: [] }),
        );
      if (url.endsWith("/event-requests/"))
        return Promise.resolve(json({ event_requests: [request()] }));
      if (url.endsWith("/event-requests/request-1/")) return Promise.resolve(json(request()));
      if (url.endsWith("/quotations/quotation-1/")) return Promise.resolve(json(quotation));
      if (url.endsWith("/reservations/reservation-1/")) return Promise.resolve(json(reservation()));
      if (url.endsWith("/reservations/reservation-1/confirm/") && init?.method === "POST") {
        reservationStatus = "confirmed";
        return Promise.resolve(json(reservation()));
      }
      if (url.endsWith("/reservations/reservation-1/cancel/") && init?.method === "POST") {
        reservationStatus = "cancelled";
        return Promise.resolve(json(reservation()));
      }
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Agenda y disponibilidad" })).toBeVisible();
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Navegación principal" })).getByRole("button", {
        name: /Solicitudes/,
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Boda/ }));

    expect(await screen.findByRole("heading", { name: "Confirmar reserva" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Monto reconocido USD"), {
      target: { value: "100.00" },
    });
    fireEvent.change(screen.getByLabelText("Fecha y hora informada"), {
      target: { value: "2026-07-31T13:00" },
    });
    fireEvent.change(screen.getByLabelText("Referencia o nota"), {
      target: { value: "Transferencia reportada" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reserva" }));

    expect(await screen.findByText("Anticipo reconocido externamente")).toBeVisible();
    expect(screen.getByText(/No procesado por Claridez/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Razón de cancelación"), {
      target: { value: "Cambio de planes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar reserva" }));

    await waitFor(() => {
      expect(screen.getAllByText("Cancelada").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Anticipo reconocido externamente")).toBeVisible();
  });
});
