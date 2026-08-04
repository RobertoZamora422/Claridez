import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CRMView } from "./CRMView";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("bandeja CRM", () => {
  it("muestra indicadores, oportunidad real y ausencia de próxima acción", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith("/crm/indicators/")) {
          return Promise.resolve(
            json({
              indicators: {
                opportunities: 1,
                open: 1,
                won: 0,
                lost: 0,
                without_next_action: 1,
                overdue_tasks: 0,
              },
            }),
          );
        }
        if (url.includes("/crm/tasks/")) return Promise.resolve(json({ tasks: [] }));
        return Promise.resolve(
          json({
            opportunities: [
              {
                id: "request-1",
                person: {
                  id: "person-1",
                  full_name: "María Torres",
                  phone_e164: "+593999999999",
                  email: null,
                  revision: 1,
                  has_interest_history: true,
                  is_client: false,
                },
                event_type: "Boda",
                starts_at: "2026-09-01T20:00:00Z",
                ends_at: "2026-09-02T02:00:00Z",
                status: "new",
                result: "open",
                origin: "referral",
                origin_detail: null,
                responsible_membership_id: "membership-1",
                closed_reason: null,
                revision: 1,
                next_action: null,
                updated_at: "2026-08-02T12:00:00Z",
              },
            ],
          }),
        );
      }),
    );

    render(
      <CRMView
        organizationId="org-1"
        timeZone="America/Guayaquil"
        capabilities={new Set(["sales:read", "person:read", "task:manage"])}
      />,
    );

    expect(await screen.findByRole("heading", { name: "CRM y seguimiento" })).toBeVisible();
    expect(await screen.findByText("María Torres")).toBeVisible();
    expect(screen.getAllByText("Sin próxima acción").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Indicadores de seguimiento")).toBeVisible();
  });

  it("fusiona desde coincidencias seleccionadas sin pedir UUID ni revisiones", async () => {
    let mergePayload: Record<string, unknown> | null = null;
    const viewedPerson = {
      id: "11111111-1111-4111-8111-111111111111",
      full_name: "Persona abierta",
      phone_e164: "+593991111111",
      email: "abierta@example.com",
      revision: 3,
      commercial_type: "lead" as const,
    };
    const targetPerson = {
      id: "22222222-2222-4222-8222-222222222222",
      full_name: "Coincidencia canónica",
      phone_e164: "+593992222222",
      email: "canonica@example.com",
      revision: 7,
      commercial_type: "client" as const,
    };
    const overview = (person: typeof viewedPerson | typeof targetPerson) => ({
      person: {
        ...person,
        has_interest_history: true,
        is_client: person.commercial_type === "client",
      },
      opportunities: [],
      interactions: [],
      tasks: [],
      consent: { person_id: person.id, effective: [], events: [] },
      timeline: [],
    });

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith("/crm/indicators/")) {
          return Promise.resolve(
            json({
              indicators: {
                opportunities: 0,
                open: 0,
                won: 0,
                lost: 0,
                without_next_action: 0,
                overdue_tasks: 0,
              },
            }),
          );
        }
        if (url.includes("/crm/tasks/")) return Promise.resolve(json({ tasks: [] }));
        if (url.endsWith(`/crm/people/${viewedPerson.id}/`)) {
          return Promise.resolve(json(overview(viewedPerson)));
        }
        if (url.endsWith(`/crm/people/${targetPerson.id}/`)) {
          return Promise.resolve(json(overview(targetPerson)));
        }
        if (url.includes("/people/?q=Persona%20abierta")) {
          return Promise.resolve(json({ people: [viewedPerson] }));
        }
        if (url.includes("/people/?q=canonica%40example.com")) {
          return Promise.resolve(json({ people: [targetPerson] }));
        }
        if (url.endsWith("/people/merge/") && init?.method === "POST") {
          if (typeof init.body !== "string") throw new TypeError("Se esperaba JSON serializado.");
          mergePayload = JSON.parse(init.body) as Record<string, unknown>;
          return Promise.resolve(
            json({
              id: "33333333-3333-4333-8333-333333333333",
              canonical_person_id: targetPerson.id,
            }),
          );
        }
        return Promise.resolve(json({ opportunities: [] }));
      }),
    );

    render(
      <CRMView
        organizationId="org-merge"
        timeZone="America/Guayaquil"
        capabilities={new Set(["person:merge"])}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Buscar o deduplicar persona"), {
      target: { value: "Persona abierta" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    fireEvent.click(await screen.findByRole("button", { name: /Persona abierta/ }));

    expect(await screen.findByRole("heading", { name: "Fusionar duplicado" })).toBeVisible();
    expect(screen.queryByLabelText("ID canónico destino")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Revisión destino")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar coincidencias"), {
      target: { value: "canonica@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buscar coincidencias" }));
    fireEvent.click(await screen.findByRole("button", { name: /Coincidencia canónica/ }));
    expect(screen.getByText("Origen")).toBeVisible();
    expect(screen.getByText("Destino canónico")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Razón obligatoria"), {
      target: { value: "Ambos registros corresponden a la misma persona." },
    });
    fireEvent.click(
      screen.getByLabelText("Confirmo que revisé las coincidencias y la razón de la fusión."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirmar fusión" }));

    await waitFor(() => {
      expect(mergePayload).not.toBeNull();
    });
    expect(mergePayload).toMatchObject({
      source_person_id: viewedPerson.id,
      target_person_id: targetPerson.id,
      source_revision: 3,
      target_revision: 7,
      reason: "Ambos registros corresponden a la misma persona.",
    });
    expect(await screen.findByRole("heading", { name: targetPerson.full_name })).toBeVisible();
  });

  it("conserva la oportunidad al corregir una interacción histórica postfusión", async () => {
    let interactionPayload: Record<string, unknown> | null = null;
    const canonicalPerson = {
      id: "44444444-4444-4444-8444-444444444444",
      full_name: "Persona canónica",
      phone_e164: "+593994444444",
      email: "canonica-interaccion@example.com",
      revision: 5,
      has_interest_history: true,
      is_client: false,
    };
    const historicalInteraction = {
      id: "55555555-5555-4555-8555-555555555555",
      person_id: "66666666-6666-4666-8666-666666666666",
      event_request_id: "77777777-7777-4777-8777-777777777777",
      channel: "email",
      direction: "inbound" as const,
      occurred_at: "2026-08-01T15:00:00Z",
      responsible_membership_id: "88888888-8888-4888-8888-888888888888",
      summary: "Interacción de la persona fuente ya fusionada.",
      correction_of_id: null,
      created_at: "2026-08-01T15:01:00Z",
    };
    const overview = {
      person: canonicalPerson,
      opportunities: [],
      interactions: [historicalInteraction],
      tasks: [],
      consent: { person_id: canonicalPerson.id, effective: [], events: [] },
      timeline: [],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith("/crm/indicators/")) {
          return Promise.resolve(
            json({
              indicators: {
                opportunities: 1,
                open: 1,
                won: 0,
                lost: 0,
                without_next_action: 1,
                overdue_tasks: 0,
              },
            }),
          );
        }
        if (url.includes("/crm/tasks/")) return Promise.resolve(json({ tasks: [] }));
        if (url.includes("/people/?q=Persona%20can%C3%B3nica")) {
          return Promise.resolve(json({ people: [canonicalPerson] }));
        }
        if (url.endsWith(`/crm/people/${canonicalPerson.id}/`)) {
          return Promise.resolve(json(overview));
        }
        if (url.endsWith("/crm/interactions/") && init?.method === "POST") {
          if (typeof init.body !== "string") throw new TypeError("Se esperaba JSON serializado.");
          interactionPayload = JSON.parse(init.body) as Record<string, unknown>;
          return Promise.resolve(json({ id: "correction-1" }));
        }
        return Promise.resolve(json({ opportunities: [] }));
      }),
    );

    render(
      <CRMView
        organizationId="org-interaction"
        timeZone="America/Guayaquil"
        capabilities={new Set(["interaction:record"])}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Buscar o deduplicar persona"), {
      target: { value: "Persona canónica" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    fireEvent.click(await screen.findByRole("button", { name: /Persona canónica/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Corregir con nueva entrada" }));
    fireEvent.change(screen.getByLabelText("Resumen minimizado"), {
      target: { value: "Corrección enlazada sin cambiar la oportunidad." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar evidencia" }));

    await waitFor(() => {
      expect(interactionPayload).not.toBeNull();
    });
    expect(interactionPayload).toMatchObject({
      person_id: canonicalPerson.id,
      event_request_id: historicalInteraction.event_request_id,
      correction_of_id: historicalInteraction.id,
      summary: "Corrección enlazada sin cambiar la oportunidad.",
    });
  });
});
