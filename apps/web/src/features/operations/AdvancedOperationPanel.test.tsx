import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdvancedOperation, OperationEvent } from "../../api";
import { AdvancedOperationPanel } from "./AdvancedOperationPanel";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  return input instanceof URL ? input.href : input.url;
}

const reservationId = "11111111-1111-4111-8111-111111111111";
const detail: OperationEvent = {
  reservation_id: reservationId,
  event: {
    event_type_id: "22222222-2222-4222-8222-222222222222",
    event_type: "Boda",
    venue: { id: "33333333-3333-4333-8333-333333333333", name: "Sede" },
    space: { id: "44444444-4444-4444-8444-444444444444", name: "Salón" },
    starts_at: "2026-10-08T23:00:00Z",
    ends_at: "2026-10-09T04:00:00Z",
    timezone: "America/Guayaquil",
    estimated_guests: 90,
    general_need: "Recepción",
  },
  contact: { display_name: "Contacto" },
  preparation: {
    status: "completed",
    revision: 12,
    responsible: null,
    baseline_version: "operations-5.2-v1",
    ready_at: "2026-10-08T20:00:00Z",
    ready_by: null,
    started_at: "2026-10-08T23:00:00Z",
    started_by: null,
    completed_at: "2026-10-09T04:00:00Z",
    completed_by: null,
    attention: {
      pending_count: 0,
      overdue_count: 0,
      blocked_count: 0,
      is_overdue: false,
      is_upcoming: false,
      is_ready: false,
      has_blockers: false,
      responsible_unavailable: false,
    },
  },
};

const advanced: AdvancedOperation = {
  snapshot: {
    id: "55555555-5555-4555-8555-555555555555",
    source_kind: "organization",
    source_version: "template:v2",
    event_type_label: "Boda",
    content_sha256: "a".repeat(64),
    roles: [],
  },
  verifications: [
    {
      id: "66666666-6666-4666-8666-666666666666",
      source_key: "post",
      phase: "post_event",
      title: "Evidencia final validada",
      is_required: true,
      role_key: "",
      position: 1,
      status: "completed",
      status_reason: "",
      completed_at: "2026-10-09T05:00:00Z",
      revision: 2,
      events: [],
    },
  ],
  phase_facts: [],
  responsibilities: [],
  incidents: [
    {
      id: "77777777-7777-4777-8777-777777777777",
      incident_type: "resource",
      severity: "medium",
      status: "contained",
      description: "Faltante conocido",
      impact: "Alternativa operacional aplicada",
      follow_up: "Confirmar reposición con el proveedor",
      responsible_membership_id: null,
      reported_at: "2026-10-08T23:30:00Z",
      revision: 2,
      events: [],
    },
  ],
  changes: [],
  resource_windows: [
    {
      id: "88888888-8888-4888-8888-888888888888",
      resource_id: "99999999-9999-4999-8999-999999999999",
      quantity: "1.000000",
      starts_at: "2026-10-08T22:30:00Z",
      ends_at: "2026-10-09T04:30:00Z",
      window_revision: 1,
      source_kind: "organization_template",
    },
  ],
  resources: [
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      operational_window_id: "88888888-8888-4888-8888-888888888888",
      resource_name: "Equipo de respaldo",
      status: "shortage",
      quantity: "1.000000",
      supplier_names: ["Proveedor A"],
      assignments: [],
    },
  ],
  evidence: [],
  close: null,
  metrics: {
    readiness_seconds: 3600,
    setup_seconds: 2700,
    execution_seconds: 18000,
    teardown_seconds: 1800,
    incident_count: 1,
    resource_shortage_count: 1,
  },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("operación avanzada P13", () => {
  it("presenta snapshot, métricas observadas, fases, incidencias y procedencia de recursos", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json(advanced))),
    );
    render(
      <AdvancedOperationPanel
        organizationId="org-1"
        detail={detail}
        assignees={[]}
        canManage={false}
        canExecute={false}
        canManageIncidents={false}
        canAuthorizeChanges={false}
        canManageEvidence={false}
        canClose
        onPreparationReload={() => Promise.resolve()}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Operación avanzada" })).toBeVisible();
    expect(screen.getByText(/template:v2/)).toBeVisible();
    expect(screen.getByText("45 min")).toBeVisible();
    expect(screen.getByText("300 min")).toBeVisible();
    expect(screen.getByText("30 min")).toBeVisible();
    expect(screen.getByText("Evidencia final validada")).toBeVisible();
    expect(screen.getByText("Faltante conocido")).toBeVisible();
    expect(screen.getByText(/Confirmar reposición con el proveedor/)).toBeVisible();
    expect(screen.getByText("Equipo de respaldo")).toBeVisible();
    expect(screen.getByText(/Proveedor A/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Cerrar postevento" })).toBeDisabled();
    expect(screen.getByText(/Completa o resuelve las incidencias incompatibles/)).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Registrar inicio" })).toHaveLength(2);
    for (const button of screen.getAllByRole("button", { name: "Registrar inicio" })) {
      expect(button).toBeDisabled();
    }
  });

  it("exige responsable y seguimiento antes de contener y los persiste por el ledger", async () => {
    const openIncident = {
      ...advanced.incidents[0],
      status: "open" as const,
      follow_up: "",
      responsible_membership_id: null,
      revision: 1,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (!init?.method || init.method === "GET") {
        return Promise.resolve(json({ ...advanced, incidents: [openIncident] }));
      }
      if (url.endsWith("/amend/")) {
        return Promise.resolve(
          json({ ...openIncident, responsible_membership_id: "membership-1", revision: 2 }),
        );
      }
      return Promise.resolve(
        json({
          ...openIncident,
          status: "contained",
          responsible_membership_id: "membership-1",
          follow_up: "Confirmar la medida mañana",
          revision: 3,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AdvancedOperationPanel
        organizationId="org-1"
        detail={detail}
        assignees={[{ membership_id: "membership-1", display_name: "Ana", role: "operaciones" }]}
        canManage={false}
        canExecute={false}
        canManageIncidents
        canAuthorizeChanges={false}
        canManageEvidence={false}
        canClose
        onPreparationReload={() => Promise.resolve()}
      />,
    );

    const contain = await screen.findByRole("button", { name: "Contener" });
    expect(contain).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Responsable para Faltante conocido"), {
      target: { value: "membership-1" },
    });
    fireEvent.change(screen.getByLabelText("Seguimiento para Faltante conocido"), {
      target: { value: "Confirmar la medida mañana" },
    });
    expect(contain).toBeEnabled();
    fireEvent.click(contain);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => requestUrl(url).endsWith("/transition/"))).toBe(
        true,
      );
    });
    const transitionCall = fetchMock.mock.calls.find(([url]) =>
      requestUrl(url).endsWith("/transition/"),
    );
    const transitionBody = transitionCall?.[1]?.body;
    expect(typeof transitionBody).toBe("string");
    if (typeof transitionBody !== "string") {
      throw new Error("La transición debe enviarse como JSON serializado.");
    }
    expect(JSON.parse(transitionBody)).toMatchObject({
      status: "contained",
      follow_up: "Confirmar la medida mañana",
    });
  });
});
