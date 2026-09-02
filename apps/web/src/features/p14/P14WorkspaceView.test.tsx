import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { P14WorkspaceView } from "./P14WorkspaceView";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
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

describe("workspace P14", () => {
  it("materializa únicamente las áreas autorizadas y no ofrece restauración universal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = urlOf(input);
        if (url.endsWith("/public-forms/")) return Promise.resolve(json({ forms: [] }));
        if (url.endsWith("/communications/templates/"))
          return Promise.resolve(json({ templates: [] }));
        if (url.endsWith("/communications/deliveries/"))
          return Promise.resolve(json({ deliveries: [] }));
        if (url.endsWith("/communications/preferences/"))
          return Promise.resolve(json({ preferences: [] }));
        return Promise.resolve(json({}));
      }),
    );
    render(
      <P14WorkspaceView
        organizationId="org-1"
        timezone="America/Guayaquil"
        capabilities={
          new Set([
            "public_form:read",
            "communication_template:read",
            "communication_delivery:read",
            "communication_preference:read",
            "communication_preference:suppress",
          ])
        }
      />,
    );

    expect(await screen.findByRole("heading", { name: "Formularios públicos" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Entregas y fallos" })).toBeVisible();
    expect(screen.getByText("No hay preferencias o supresiones registradas.")).toBeVisible();
    expect(screen.queryByRole("option", { name: /Liberar supresión/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Grants de Portal" })).not.toBeInTheDocument();
  });
});
