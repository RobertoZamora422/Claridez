import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfigurationView } from "./ConfigurationView";

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

describe("configuración funcional P6", () => {
  it("actualiza solo los datos funcionales y conserva visible la frontera de seguridad", async () => {
    const renamed = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/configuration/") && init?.method !== "PATCH")
        return Promise.resolve(
          json({
            organization_id: "org-1",
            name: "Salón Horizonte",
            currency: "USD",
            timezone: "America/Guayaquil",
          }),
        );
      if (url.endsWith("/configuration/") && init?.method === "PATCH")
        return Promise.resolve(json({}));
      if (url.endsWith("/venues/")) return Promise.resolve(json({ venues: [] }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConfigurationView organizationId="org-1" canManage onOrganizationRenamed={renamed} />);
    expect(
      await screen.findByText(/Las membresías y la seguridad sensible no se administran aquí/),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Nombre del negocio"), {
      target: { value: "Centro Horizonte" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }));

    await waitFor(() => {
      expect(renamed).toHaveBeenCalledWith("Centro Horizonte");
    });
    const call = fetchMock.mock.calls.find(
      ([input, init]) => urlOf(input).endsWith("/configuration/") && init?.method === "PATCH",
    );
    const requestBody = call?.[1]?.body;
    if (typeof requestBody !== "string") throw new Error("La solicitud no contiene JSON.");
    expect(JSON.parse(requestBody)).toEqual({
      name: "Centro Horizonte",
      currency: "USD",
      timezone: "America/Guayaquil",
    });
  });
});
