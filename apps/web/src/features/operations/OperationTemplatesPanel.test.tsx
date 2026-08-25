import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperationTemplatesPanel } from "./OperationTemplatesPanel";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const draft = {
  id: "11111111-1111-4111-8111-111111111111",
  template_id: "22222222-2222-4222-8222-222222222222",
  event_type_id: "33333333-3333-4333-8333-333333333333",
  name: "Plan boda",
  version: 1,
  status: "draft",
  content_sha256: "",
  published_at: null,
  definitions: { readiness: [], verifications: [], roles: [], resource_needs: [] },
} as const;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("plantillas operativas P13", () => {
  it("explica el fallback inmutable y no ofrece mutaciones sin capability", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json([draft]))),
    );
    render(<OperationTemplatesPanel organizationId="org-1" canManage={false} />);

    fireEvent.click(screen.getByText("Plantillas operativas versionadas"));
    expect(await screen.findByText(/operations-p13-system-v1/)).toBeVisible();
    expect(await screen.findByText("Plan boda")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Publicar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nueva versión" })).not.toBeInTheDocument();
  });

  it("publica mediante comando explícito y recarga la versión congelada", async () => {
    let published = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/${draft.id}/publish/`) && init?.method === "POST") {
        published = true;
        return Promise.resolve(json({ ...draft, status: "published" }));
      }
      return Promise.resolve(json([{ ...draft, status: published ? "published" : "draft" }]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<OperationTemplatesPanel organizationId="org-1" canManage />);

    fireEvent.click(screen.getByText("Plantillas operativas versionadas"));
    fireEvent.click(await screen.findByRole("button", { name: "Publicar" }));
    expect(await screen.findByText("Versión publicada.")).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Retirar" })).toBeVisible();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/${draft.id}/publish/`),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
