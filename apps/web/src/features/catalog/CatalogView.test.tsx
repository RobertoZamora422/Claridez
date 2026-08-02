import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogView } from "./CatalogView";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("administración funcional del catálogo", () => {
  it("crea un paquete con composición explícita y sin inventar su precio", async () => {
    const items = [
      {
        id: "service-1",
        kind: "service",
        name: "Coordinación",
        description: null,
        unit_label: "evento",
        is_active: true,
        revision: 1,
        revision_id: "revision-1",
        components: [],
        current_price: null,
        prices: [],
      },
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/event-types/")) return Promise.resolve(json({ event_types: [] }));
      if (url.endsWith("/catalog/items/") && init?.method !== "POST")
        return Promise.resolve(json({ items }));
      if (url.endsWith("/catalog/items/") && init?.method === "POST")
        return Promise.resolve(json({ ...items[0], id: "package-1", kind: "package" }, 201));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CatalogView
        organizationId="org-1"
        timeZone="America/Guayaquil"
        canManage
        canReadPrices
        canManagePrices
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Catálogo, paquetes y precios" }),
    ).toBeVisible();
    const form = screen.getByRole("heading", { name: "Nuevo ítem" }).closest("form");
    if (!form) throw new Error("No se encontró el formulario de catálogo.");
    fireEvent.change(within(form).getByLabelText("Tipo"), { target: { value: "package" } });
    fireEvent.change(within(form).getByLabelText("Nombre"), {
      target: { value: "Paquete esencial" },
    });
    fireEvent.change(within(form).getByLabelText("Unidad"), { target: { value: "evento" } });
    fireEvent.click(within(form).getByRole("button", { name: "Añadir componente" }));
    fireEvent.click(within(form).getByRole("button", { name: "Crear ítem" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => urlOf(input).endsWith("/catalog/items/") && init?.method === "POST",
        ),
      ).toBe(true);
    });
    const call = fetchMock.mock.calls.find(
      ([input, init]) => urlOf(input).endsWith("/catalog/items/") && init?.method === "POST",
    );
    const requestBody = call?.[1]?.body;
    if (typeof requestBody !== "string") throw new Error("La solicitud no contiene JSON.");
    expect(JSON.parse(requestBody)).toMatchObject({
      kind: "package",
      name: "Paquete esencial",
      components: [{ item_id: "service-1", quantity: "1.000" }],
    });
  });

  it("permite consulta comercial de precios sin controles de administración", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.endsWith("/event-types/")) return Promise.resolve(json({ event_types: [] }));
      if (url.endsWith("/catalog/items/"))
        return Promise.resolve(
          json({
            items: [
              {
                id: "service-readonly",
                kind: "service",
                name: "Coordinación",
                description: null,
                unit_label: "evento",
                is_active: true,
                revision: 1,
                revision_id: "revision-readonly",
                components: [],
                current_price: {
                  id: "price-readonly",
                  amount: "125.00",
                  currency: "USD",
                  valid_from: "2026-08-01T00:00:00Z",
                  valid_until: null,
                  revision: 1,
                },
                prices: [],
              },
            ],
          }),
        );
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CatalogView
        organizationId="org-1"
        timeZone="America/Guayaquil"
        canManage={false}
        canReadPrices
        canManagePrices={false}
      />,
    );
    expect(await screen.findByText("$125.00")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Crear ítem" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Registrar precio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar revisión" })).not.toBeInTheDocument();
  });
});
