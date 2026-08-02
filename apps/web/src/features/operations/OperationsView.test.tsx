import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperationsView } from "./OperationsView";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const summary = {
  reservation_id: "11111111-1111-4111-8111-111111111111",
  event: {
    event_type: "Boda",
    starts_at: "2026-09-12T20:00:00Z",
    ends_at: "2026-09-13T02:00:00Z",
    timezone: "America/Guayaquil",
    estimated_guests: 90,
    general_need: "Recepción y ceremonia",
  },
  contact: { display_name: "Contacto Operativo" },
  preparation: {
    status: "preparing",
    revision: 1,
    responsible: null,
    baseline_version: "operations-5.2-v1",
    ready_at: null,
    started_at: null,
    completed_at: null,
    attention: {
      pending_count: 7,
      overdue_count: 0,
      blocked_count: 0,
      is_overdue: false,
      is_upcoming: false,
      is_ready: false,
      has_blockers: false,
      responsible_unavailable: false,
    },
  },
} as const;

const item = {
  id: "22222222-2222-4222-8222-222222222222",
  client_request_id: "33333333-3333-4333-8333-333333333333",
  baseline_key: "space_layout",
  section: "definitions",
  position: 1,
  title: "Confirmar distribución del espacio",
  is_required: true,
  responsible: null,
  due_on: "2026-09-05",
  status: "pending",
  notes: "",
  status_note: "",
  revision: 1,
} as const;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("bandeja y detalle operativo", () => {
  it("comunica estados por texto y muestra el checklist en modo lectura", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.includes("/operations/events/?"))
          return Promise.resolve(json({ results: [summary], next_cursor: null }));
        if (url.endsWith(`/operations/events/${summary.reservation_id}/`))
          return Promise.resolve(
            json({
              ...summary,
              contact: { display_name: "Contacto Operativo", phone_e164: "+593991234567" },
              preparation: { ...summary.preparation, items: [item] },
            }),
          );
        return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
      }),
    );

    render(<OperationsView organizationId="org-1" canManage={false} canExecute={false} />);

    expect(await screen.findByRole("heading", { name: "Próximos eventos" })).toBeVisible();
    expect(
      await screen.findByText("En preparación", { selector: "span.status--preparing" }),
    ).toBeVisible();
    expect(screen.queryByText("+593991234567")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Boda/ }));
    expect(await screen.findByRole("heading", { name: "Checklist" })).toBeVisible();
    expect(screen.getByText("Confirmar distribución del espacio")).toBeVisible();
    expect(screen.getByText(/\+593991234567/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Guardar ítem" })).not.toBeInTheDocument();
  });

  it("explica por texto los requisitos de listo y ofrece reordenamiento por teclado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.includes("/operations/assignees/")) return Promise.resolve(json({ assignees: [] }));
        if (url.includes("/operations/events/?"))
          return Promise.resolve(json({ results: [summary], next_cursor: null }));
        if (url.endsWith(`/operations/events/${summary.reservation_id}/`))
          return Promise.resolve(
            json({ ...summary, preparation: { ...summary.preparation, items: [item] } }),
          );
        return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
      }),
    );

    render(<OperationsView organizationId="org-1" canManage canExecute={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /Boda/ }));
    expect(await screen.findByText("Antes de declarar listo:")).toBeVisible();
    expect(screen.getByRole("button", { name: "Declarar evento listo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Subir" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bajar" })).toBeDisabled();
  });

  it("presenta un vacío real sin ofrecer creación comercial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json({ results: [], next_cursor: null }))),
    );
    render(<OperationsView organizationId="org-1" canManage={false} canExecute={false} />);
    expect(await screen.findByText("No hay eventos confirmados en este periodo")).toBeVisible();
    expect(screen.queryByRole("button", { name: /crear reserva/i })).not.toBeInTheDocument();
  });
});
