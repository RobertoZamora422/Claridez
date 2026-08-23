import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResourcesView } from "./ResourcesView";

const organizationId = "30000000-0000-4000-8000-000000000001";

function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

const overview = {
  organization_id: organizationId,
  capabilities: ["resource:read_availability"],
  availability: [
    {
      resource_id: "resource-1",
      name: "Mesas",
      nature: "reusable_pool",
      unit: "unidad",
      declared_capacity: "10.000000",
      available: "0.000000",
      shortage: true,
    },
  ],
  resources: [],
  units: [],
  conversions: [],
  locations: [],
  balances: [],
  assets: [],
  movements: [],
  requirements: [],
  assignments: [],
  unavailability: [],
  maintenance: [],
  suppliers: [],
  purchases: [],
  receipts: [],
};

describe("ResourcesView", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("/auth/csrf/")) return Promise.resolve(response({ csrf_token: "csrf" }));
      if (url.endsWith("/resources/overview/")) return Promise.resolve(response(overview));
      if (url.endsWith("/resources/suppliers/create/") && init?.method === "POST")
        return Promise.resolve(response({ id: "supplier-1" }, 201));
      throw new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`);
    });
  });

  it("muestra capacidad no disponible como faltante sin inventarla", async () => {
    render(
      <ResourcesView
        organizationId={organizationId}
        capabilities={new Set(["resource:read_availability"])}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Proveedores, recursos e inventario" }),
    ).toBeVisible();
    expect(screen.getByText("Faltante")).toBeVisible();
    expect(screen.getByText(/0.000000 unidad/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Crear proveedor" })).not.toBeInTheDocument();
  });

  it("expone comandos solo con la capacidad atómica y envía idempotencia", async () => {
    render(
      <ResourcesView
        organizationId={organizationId}
        capabilities={new Set(["resource:read_availability", "supplier:manage_profile"])}
      />,
    );
    await screen.findByRole("heading", { name: "Proveedores, recursos e inventario" });
    fireEvent.click(screen.getByRole("button", { name: "Proveedores y compras" }));
    const form = screen.getByRole("heading", { name: "Nuevo proveedor" }).closest("form");
    if (form === null) throw new Error("No se encontró el comando de proveedor.");
    fireEvent.change(within(form).getByLabelText("Razón social"), {
      target: { value: "Proveedor de prueba" },
    });
    fireEvent.change(within(form).getByLabelText("Identificación fiscal"), {
      target: { value: "1799999999001" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Crear proveedor" }));
    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) =>
            requestUrl(input).endsWith("/resources/suppliers/create/") && init?.method === "POST",
        );
      expect(call).toBeDefined();
      expect(new Headers(call?.[1]?.headers).get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
    });
  });
});
