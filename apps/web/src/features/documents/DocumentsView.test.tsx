import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentsView } from "./DocumentsView";
import { ExternalDocumentView } from "./ExternalDocumentView";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("P9 documentos", () => {
  it("muestra la ausencia honesta de expediente y la gestión autorizada", async () => {
    const rootId = "11111111-1111-4111-8111-111111111111";
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/documents/templates/")) return Promise.resolve(json({ templates: [] }));
      if (url.endsWith("/documents/retention/"))
        return Promise.resolve(json({ policies: [], assignments: [], holds: [], events: [] }));
      if (url.includes("/documents/records/?"))
        return Promise.resolve(
          json({
            status: "no_contract_issued",
            label: "sin contrato emitido",
            root_reservation_id: rootId,
            instruments: [],
            external_files: [],
          }),
        );
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <DocumentsView
        organizationId="org-1"
        capabilities={
          new Set([
            "document_template:read",
            "document_template:manage",
            "contractual_record:read",
            "contractual_instrument:issue",
            "document_retention:read",
            "document_retention:manage",
          ])
        }
      />,
    );
    expect(await screen.findByRole("heading", { name: "Contratos y documentos" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Crear plantilla y borrador v1" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("UUID de reserva raíz"), { target: { value: rootId } });
    fireEvent.click(screen.getByRole("button", { name: "Consultar" }));
    expect(await screen.findByRole("heading", { name: "Sin contrato emitido" })).toBeVisible();
    expect(screen.getByText("No existe un expediente ficticio para esta reserva.")).toBeVisible();
  });

  it("intercambia el token, limpia la URL y acepta el artefacto exacto", async () => {
    const grantToken = "g".repeat(64);
    window.history.replaceState({}, "", `/documents/access#${grantToken}`);
    const replaceState = vi.spyOn(window.history, "replaceState");
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/exchange/")) return Promise.resolve(json({ status: "session_created" }));
      if (url.endsWith("/session/"))
        return Promise.resolve(
          json({
            title: "Contrato de evento",
            issued_version_id: "version-1",
            instrument_type: "main_contract",
            version: 1,
            issued_at: "2026-08-12T12:00:00Z",
            artifact: {
              id: "artifact-1",
              sha256: "a".repeat(64),
              size_bytes: 2048,
              media_type: "application/pdf",
            },
            permissions: { read: true, download: true, accept: true },
            manifestation: {
              text: "Acepto el documento exacto.",
              version: "claridez-acceptance-es-v1",
            },
          }),
        );
      if (url.endsWith("/challenge/"))
        return Promise.resolve(json({ challenge_token: "c".repeat(64) }, 201));
      if (url.endsWith("/accept/"))
        return Promise.resolve(json({ status: "accepted", artifact_sha256: "a".repeat(64) }, 201));
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ExternalDocumentView token={grantToken} />);
    expect(await screen.findByRole("heading", { name: "Contrato de evento" })).toBeVisible();
    expect(replaceState).toHaveBeenCalledWith({}, "", "/documents/external");
    expect(window.location.hash).toBe("");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/external/documents/exchange/");
    expect(screen.getByTitle("Documento: Contrato de evento")).toHaveAttribute(
      "src",
      "/api/v1/external/documents/artifact/",
    );
    fireEvent.change(screen.getByLabelText("Nombre de quien acepta"), {
      target: { value: "María Contraparte" },
    });
    fireEvent.click(
      screen.getByLabelText("Manifiesto afirmativamente mi aceptación del documento mostrado."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Aceptar este documento" }));
    expect(
      await screen.findByText("Tu aceptación quedó registrada para este artefacto exacto."),
    ).toBeVisible();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(4);
    });
  });

  it("elimina el fragmento aunque el intercambio sea inválido y no persiste el secreto", async () => {
    const grantToken = "s".repeat(64);
    window.history.replaceState({}, "", `/documents/access#${grantToken}`);
    const replaceState = vi.spyOn(window.history, "replaceState");
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      () =>
        Promise.resolve(
          json(
            { error: { code: "not_found", message: "El acceso documental no está disponible." } },
            404,
          ),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ExternalDocumentView token={grantToken} />);

    expect(await screen.findByRole("heading", { name: "Enlace no disponible" })).toBeVisible();
    expect(replaceState).toHaveBeenCalledWith({}, "", "/documents/external");
    expect(window.location.pathname).toBe("/documents/external");
    expect(window.location.hash).toBe("");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/external/documents/exchange/");
    expect(storageWrite).not.toHaveBeenCalled();
  });
});
