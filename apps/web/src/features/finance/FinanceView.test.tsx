import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinanceView } from "./FinanceView";

const organizationId = "30000000-0000-4000-8000-000000000001";
const metric = {
  recognized_revenue: "1000.00",
  direct_cost: "200.00",
  variable_expense: "50.00",
  recurring_expense: "100.00",
  gross_margin: "800.00",
  contribution_margin: "750.00",
  operating_result: "650.00",
  profitability_percentage: "65.00",
  p10_cash: "300.00",
  p11_cash: "-150.00",
  net_cash_flow: "150.00",
};
const emptyMetric = Object.fromEntries(
  Object.keys(metric).map((key) => [key, key === "profitability_percentage" ? null : "0.00"]),
);
const overview = {
  organization_id: organizationId,
  currency: "USD",
  timezone: "America/Guayaquil",
  period: null,
  filters: { root_reservation_id: null, venue_id: null },
  ordinary: metric,
  prior_period_adjustments: { ...emptyMetric, direct_cost: "10.00" },
  presented: metric,
  events: [
    {
      root_reservation_id: "10000000-0000-4000-8000-000000000001",
      recognized_venue_id: "20000000-0000-4000-8000-000000000001",
      baseline_plan_revision_id: "40000000-0000-4000-8000-000000000001",
      baseline_planned_cost: "180.00",
      cost_variance: "20.00",
      metrics: metric,
    },
  ],
  categories: [
    { id: "50000000-0000-4000-8000-000000000001", kind: "direct_cost", name: "Catering" },
  ],
  periods: [],
  direct_cost_plans: [],
  direct_costs: [],
  cost_evidence: [],
  expenses: [],
  recurring_rules: [],
  budgets: [],
  cash_movements: [],
  recognition_adjustments: [],
  p10_source_references: [],
};

function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

describe("FinanceView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("/auth/csrf/")) return Promise.resolve(response({ csrf_token: "token" }));
      if (url.includes("/finance/overview/")) return Promise.resolve(response(overview));
      if (url.endsWith("/finance/evidence-context/"))
        return Promise.resolve(response({ categories: overview.categories, events: [] }));
      if (url.endsWith("/finance/categories/") && init?.method === "POST")
        return Promise.resolve(response({ id: crypto.randomUUID() }, 201));
      throw new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`);
    });
  });

  it("presenta las fórmulas del backend y separa ajustes anteriores", async () => {
    render(
      <FinanceView organizationId={organizationId} capabilities={new Set(["finance:read"])} />,
    );
    expect(
      await screen.findByRole("heading", { name: "Costos, gastos, flujo y rentabilidad" }),
    ).toBeVisible();
    expect(screen.getByText("Ajustes de periodos anteriores")).toBeVisible();
    expect(screen.getByText("Rentabilidad por evento")).toBeVisible();
    expect(screen.getByText("65.00%")).toBeVisible();
    expect(screen.getByRole("link", { name: "Exportar CSV" })).toHaveAttribute(
      "href",
      `/api/v1/organizations/${organizationId}/finance/export/`,
    );
  });

  it("envía comandos con CSRF e idempotencia desde capacidades del backend", async () => {
    render(
      <FinanceView
        organizationId={organizationId}
        capabilities={new Set(["finance:read", "finance:manage_categories"])}
      />,
    );
    const form = (await screen.findByRole("heading", { name: "Nueva categoría" })).closest("form");
    expect(form).not.toBeNull();
    if (form === null) return;
    fireEvent.change(within(form).getByLabelText("Nombre"), { target: { value: "Logística" } });
    fireEvent.click(within(form).getByRole("button", { name: "Crear categoría" }));
    await waitFor(() => {
      const request = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) =>
            requestUrl(input).endsWith("/finance/categories/") && init?.method === "POST",
        );
      expect(request).toBeDefined();
      const headers = new Headers(request?.[1]?.headers);
      expect(headers.get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
      expect(headers.get("X-CSRFToken")).toBe("token");
    });
  });
});
