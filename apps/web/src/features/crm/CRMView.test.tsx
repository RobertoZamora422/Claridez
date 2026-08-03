import { cleanup, render, screen } from "@testing-library/react";
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
});
