import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReceivablesView } from "./ReceivablesView";

const obligation = {
  id: "10000000-0000-4000-8000-000000000001",
  root_reservation_id: "10000000-0000-4000-8000-000000000002",
  current_reservation_id: "10000000-0000-4000-8000-000000000002",
  counterparty_person_id: "10000000-0000-4000-8000-000000000003",
  counterparty_name: "María Pérez",
  currency: "USD",
  original_total: "1617.20",
  adjusted_total: "1617.20",
  applied_total: "300.00",
  balance: "1317.20",
  derived_status: "partial",
  reservation_status: "confirmed",
  financial_review_required: false,
  schedule_configured: false,
  schedule: [],
};

const payment = {
  id: "20000000-0000-4000-8000-000000000001",
  counterparty_person_id: obligation.counterparty_person_id,
  root_reservation_id: obligation.root_reservation_id,
  amount: "400.00",
  currency: "USD",
  reported_at: "2026-08-14T15:00:00Z",
  method: "bank_transfer",
  reference: "TRX-001",
  provenance: "manual",
  evidence_level: "internal_report",
  possible_duplicate: false,
  unapplied_amount: "100.00",
};

function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

describe("ReceivablesView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("/auth/csrf/")) return Promise.resolve(response({ csrf_token: "token" }));
      if (url.endsWith("/portfolio/"))
        return Promise.resolve(response({ obligations: [obligation], currency_groups: [] }));
      if (url.endsWith("/payments/") && (init?.method ?? "GET") === "GET")
        return Promise.resolve(response({ payments: [payment] }));
      if (url.endsWith("/aging/"))
        return Promise.resolve(
          response({
            entries: [
              {
                obligation_id: obligation.id,
                bucket: "unscheduled",
                open_amount: "1317.20",
                currency: "USD",
                days_overdue: null,
              },
            ],
          }),
        );
      if (url.endsWith(`/obligations/${obligation.id}/statement/`))
        return Promise.resolve(
          response({
            ...obligation,
            payments: [payment],
            applications: [],
            adjustments: [],
            refunds: [],
            reversals: [],
            receipts: [],
          }),
        );
      if (url.endsWith("/payments/") && init?.method === "POST")
        return Promise.resolve(response(payment, 201));
      throw new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`);
    });
  });

  it("presenta cartera, saldo, aging y excedente sin aplicar sin overflow autoritativo", async () => {
    render(
      <ReceivablesView
        organizationId="30000000-0000-4000-8000-000000000001"
        capabilities={new Set(["receivables:read"])}
      />,
    );
    expect(await screen.findByRole("heading", { name: "Cartera y pagos recibidos" })).toBeVisible();
    expect(screen.getByText("María Pérez")).toBeVisible();
    expect(screen.getByText("Sin vencimiento configurado")).toBeVisible();
    expect(await screen.findByRole("region", { name: "Movimientos" })).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Registrar pago externo" }),
    ).not.toBeInTheDocument();
  });

  it("envía un comando monetario con CSRF e idempotency key", async () => {
    render(
      <ReceivablesView
        organizationId="30000000-0000-4000-8000-000000000001"
        capabilities={new Set(["receivables:read", "receivables:record_payment"])}
      />,
    );
    const form = (await screen.findByRole("heading", { name: "Registrar pago externo" })).closest(
      "form",
    );
    expect(form).not.toBeNull();
    if (form === null) throw new Error("No se encontró el formulario de pago.");
    const scoped = within(form);
    fireEvent.change(scoped.getByLabelText("Importe USD"), { target: { value: "50.00" } });
    fireEvent.change(scoped.getByLabelText("Fecha y hora reportada"), {
      target: { value: "2026-08-14T10:30" },
    });
    fireEvent.click(scoped.getByRole("button", { name: "Registrar pago" }));
    await waitFor(() => {
      const request = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) => requestUrl(input).endsWith("/payments/") && init?.method === "POST",
        );
      expect(request).toBeDefined();
      const headers = new Headers(request?.[1]?.headers);
      expect(headers.get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
      expect(headers.get("X-CSRFToken")).toBe("token");
    });
  });
});
