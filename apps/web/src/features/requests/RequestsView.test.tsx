import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequestsView } from "./RequestsView";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("estados y representación de solicitudes", () => {
  it("muestra carga y conserva restringidos los datos personales ausentes", async () => {
    let resolveResponse: ((response: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveResponse = resolve;
          }),
      ),
    );

    render(
      <RequestsView
        organizationId="org-1"
        timeZone="America/Guayaquil"
        canManage={false}
        selectedId={null}
        onSelect={vi.fn()}
        capabilities={new Set(["sales:read"])}
      />,
    );
    expect(await screen.findByText("Cargando información…")).toBeVisible();
    resolveResponse?.(
      json({
        event_requests: [
          {
            id: "request-1",
            person: { id: "person-1", restricted: true },
            event_type: "Graduación",
            starts_at: "2026-09-12T20:00:00Z",
            ends_at: "2026-09-13T02:00:00Z",
            event_timezone: "America/Guayaquil",
            estimated_guests: 80,
            general_need: "Salón",
            notes: "",
            origin: "referral",
            status: "quoted",
            revision: 1,
            quotation_id: null,
            reservation: null,
          },
        ],
      }),
    );

    expect(await screen.findByText("Contacto restringido")).toBeVisible();
    expect(screen.queryByText(/099|@/)).not.toBeInTheDocument();
  });

  it("comunica el error real del backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json(
            { error: { code: "temporarily_unavailable", message: "Servicio no disponible." } },
            503,
          ),
        ),
      ),
    );

    render(
      <RequestsView
        organizationId="org-1"
        timeZone="America/Guayaquil"
        canManage={false}
        selectedId={null}
        onSelect={vi.fn()}
        capabilities={new Set(["sales:read"])}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Servicio no disponible.");
  });
});
