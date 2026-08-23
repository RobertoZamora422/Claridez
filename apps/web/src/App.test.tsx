import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import indexHtml from "../index.html?raw";
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
    expect(screen.getByRole("img", { name: "Claridez" })).toHaveAttribute(
      "src",
      expect.stringContaining("claridez-logo-horizontal-color"),
    );
    expect(indexHtml).toContain("<title>Claridez — Centro de control comercial</title>");
    expect(indexHtml).toContain("Claridez_Brand_Assets_v1.0/web-icons/favicon.svg");
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
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf-test" }));
      if (url === "/api/v1/organizations/")
        return Promise.resolve(json({ organizations: [organization] }));
      if (url === "/api/v1/organizations/context/") return Promise.resolve(json({ organization }));
      if (url.endsWith("/commercial/capabilities/"))
        return Promise.resolve(
          json({ capabilities: ["sales:read", "sales:manage", "availability:read"] }),
        );
      if (url.endsWith("/operations/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/configuration/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/crm/capabilities/"))
        return Promise.resolve(json({ capabilities: ["sales:read"] }));
      if (url.endsWith("/scheduling/capabilities/"))
        return Promise.resolve(json({ capabilities: ["availability:read"] }));
      if (url.endsWith("/documents/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/receivables/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/finance/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/settings/"))
        return Promise.resolve(json({ settings: { timezone: "America/Guayaquil" } }));
      if (url.endsWith("/venues/"))
        return Promise.resolve(
          json({
            venues: [
              {
                id: "venue-1",
                name: "Sede principal",
                is_active: true,
                spaces: [
                  {
                    id: "space-1",
                    name: "Espacio principal",
                    is_active: true,
                    is_primary: true,
                  },
                ],
              },
            ],
          }),
        );
      if (url.endsWith("/event-types/"))
        return Promise.resolve(
          json({ event_types: [{ id: "event-type-1", name: "Boda", is_active: true }] }),
        );
      if (url.includes("/availability/?"))
        return Promise.resolve(
          json({
            from: "2026-07-31T05:00:00Z",
            to: "2026-08-07T05:00:00Z",
            available: true,
            blocks: [],
          }),
        );
      if (url.includes("/scheduling/calendar/?"))
        return Promise.resolve(
          json({
            view: "week",
            anchor_date: "2026-08-06",
            timezone: "America/Guayaquil",
            from: "2026-08-03T05:00:00Z",
            to: "2026-08-10T05:00:00Z",
            entries: [],
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
        expect.stringContaining("/scheduling/calendar/?view=week"),
        expect.objectContaining({ credentials: "same-origin" }),
      );
    });
  });

  it("reprograma una reserva temporal desde Agenda y recarga el calendario", async () => {
    const organization = { id: "org-1", name: "Salón Horizonte", slug: "horizonte" };
    let calendarLoads = 0;
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
              "sales:read",
              "sales:manage",
              "availability:read",
              "reservation:confirm",
            ],
          }),
        );
      if (url.endsWith("/operations/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/configuration/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/crm/capabilities/")) return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/scheduling/capabilities/"))
        return Promise.resolve(
          json({ capabilities: ["availability:read", "reservation:reschedule"] }),
        );
      if (url.endsWith("/documents/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/receivables/capabilities/"))
        return Promise.resolve(
          json({
            capabilities: ["receivables:record_payment", "receivables:apply_payment"],
          }),
        );
      if (url.endsWith("/finance/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/settings/"))
        return Promise.resolve(json({ settings: { timezone: "America/Guayaquil" } }));
      if (url.endsWith("/venues/"))
        return Promise.resolve(
          json({
            venues: [
              {
                id: "venue-1",
                name: "Sede principal",
                is_active: true,
                spaces: [
                  {
                    id: "space-1",
                    name: "Espacio principal",
                    is_active: true,
                    is_primary: true,
                  },
                  {
                    id: "space-2",
                    name: "Espacio alterno",
                    is_active: true,
                    is_primary: false,
                  },
                ],
              },
            ],
          }),
        );
      if (url.includes("/scheduling/calendar/?")) {
        calendarLoads += 1;
        return Promise.resolve(
          json({
            view: "week",
            anchor_date: "2026-08-06",
            timezone: "America/Guayaquil",
            from: "2026-08-03T05:00:00Z",
            to: "2026-08-10T05:00:00Z",
            entries: [
              {
                id: "reservation-hold-1",
                type: "hold",
                status: "provisional",
                revision: 7,
                root_id: "reservation-hold-1",
                space_id: "space-1",
                space_name: "Espacio principal",
                venue_id: "venue-1",
                venue_name: "Sede principal",
                starts_at: "2026-08-07T23:00:00Z",
                ends_at: "2026-08-08T04:00:00Z",
                event_timezone: "America/Guayaquil",
                setup_minutes: 0,
                teardown_minutes: 0,
                buffer_before_minutes: 0,
                buffer_after_minutes: 0,
                is_blocking: true,
              },
            ],
          }),
        );
      }
      if (url.endsWith("/reservations/reservation-hold-1/schedule-history/"))
        return Promise.resolve(json({ results: [] }));
      if (url.endsWith("/reservations/reservation-hold-1/reschedule/") && init?.method === "POST")
        return Promise.resolve(
          json({
            previous: { reservation_id: "reservation-hold-1", status: "provisional" },
            reservation: { id: "reservation-hold-2", status: "provisional" },
            carried_item_ids: [],
          }),
        );
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Agenda y disponibilidad" })).toBeVisible();
    const [holdButton] = await screen.findAllByRole("button", { name: /Reserva temporal/ });
    if (!holdButton) throw new Error("No se encontró la reserva temporal de prueba.");
    fireEvent.click(holdButton);
    expect(await screen.findByRole("button", { name: "Confirmar" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reprogramar" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reprogramar" }));
    fireEvent.change(screen.getByLabelText("Nuevo espacio"), { target: { value: "space-2" } });
    fireEvent.change(screen.getByLabelText("Inicio local"), {
      target: { value: "2026-08-14T18:00" },
    });
    fireEvent.change(screen.getByLabelText("Fin local"), {
      target: { value: "2026-08-14T23:00" },
    });
    fireEvent.change(screen.getByLabelText("Razón"), {
      target: { value: "Cambio solicitado antes de confirmar" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reprogramación" }));

    expect(
      await screen.findByText("Reserva reprogramada. La fecha anterior permanece en la historia."),
    ).toBeVisible();
    await waitFor(() => {
      expect(calendarLoads).toBeGreaterThanOrEqual(2);
    });
    const call = fetchMock.mock.calls.find(([input, init]) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return (
        url.endsWith("/reservations/reservation-hold-1/reschedule/") && init?.method === "POST"
      );
    });
    expect(call).toBeDefined();
    const requestBody = call?.[1]?.body;
    expect(typeof requestBody).toBe("string");
    if (typeof requestBody !== "string") throw new Error("El POST no contiene JSON serializado.");
    const body = JSON.parse(requestBody) as Record<string, unknown>;
    expect(body).toMatchObject({
      revision: 7,
      space_id: "space-2",
      starts_at_local: "2026-08-14T18:00",
      ends_at_local: "2026-08-14T23:00",
      timezone: "America/Guayaquil",
      reason: "Cambio solicitado antes de confirmar",
      commercial_terms_unchanged: true,
    });
    expect(body.idempotency_key).toEqual(expect.any(String));
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
      event_type_id: "event-type-1",
      event_type: "Boda",
      venue: { id: "venue-1", name: "Sede principal" },
      space: { id: "space-1", name: "Espacio principal" },
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
      space_id: "space-1",
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
      if (url.endsWith("/operations/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/configuration/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/crm/capabilities/"))
        return Promise.resolve(
          json({
            capabilities: [
              "person:read",
              "sales:read",
              "interaction:read",
              "interaction:record",
              "task:manage",
              "consent:read",
              "consent:manage",
              "person:merge",
            ],
          }),
        );
      if (url.endsWith("/scheduling/capabilities/"))
        return Promise.resolve(
          json({
            capabilities: ["availability:read", "reservation:reschedule", "schedule:export"],
          }),
        );
      if (url.endsWith("/documents/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/receivables/capabilities/"))
        return Promise.resolve(
          json({
            capabilities: ["receivables:record_payment", "receivables:apply_payment"],
          }),
        );
      if (url.endsWith("/finance/capabilities/"))
        return Promise.resolve(json({ capabilities: [] }));
      if (url.endsWith("/settings/"))
        return Promise.resolve(json({ settings: { timezone: "America/Guayaquil" } }));
      if (url.endsWith("/venues/"))
        return Promise.resolve(
          json({
            venues: [
              {
                id: "venue-1",
                name: "Sede principal",
                is_active: true,
                spaces: [
                  {
                    id: "space-1",
                    name: "Espacio principal",
                    is_active: true,
                    is_primary: true,
                  },
                ],
              },
            ],
          }),
        );
      if (url.endsWith("/catalog/items/")) return Promise.resolve(json({ items: [] }));
      if (url.includes("/availability/?"))
        return Promise.resolve(
          json({ from: "2026-07-31T05:00:00Z", to: "2026-08-07T05:00:00Z", blocks: [] }),
        );
      if (url.includes("/scheduling/calendar/?"))
        return Promise.resolve(
          json({
            view: "week",
            anchor_date: "2026-08-06",
            timezone: "America/Guayaquil",
            from: "2026-08-03T05:00:00Z",
            to: "2026-08-10T05:00:00Z",
            entries: [],
          }),
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
