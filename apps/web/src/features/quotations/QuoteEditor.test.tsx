import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EventRequest, Quotation, QuotationVersion } from "../../api";
import { QuoteEditor } from "./QuoteEditor";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

function requestBody(init: RequestInit | undefined): unknown {
  if (typeof init?.body !== "string") throw new Error("La solicitud no contiene JSON.");
  return JSON.parse(init.body) as unknown;
}

const request = {
  id: "request-1",
  person: { id: "person-1", commercial_type: "lead", revision: 1 },
  event_type: "Boda",
  starts_at: "2026-09-12T20:00:00Z",
  ends_at: "2026-09-13T02:00:00Z",
  event_timezone: "America/Guayaquil",
  estimated_guests: 120,
  general_need: "Salón",
  notes: "",
  origin: "whatsapp",
  status: "quoted",
  revision: 2,
  quotation_id: "quotation-1",
  reservation: null,
} satisfies EventRequest;

function version(status: "draft" | "issued"): QuotationVersion {
  return {
    id: "version-1",
    version: 1,
    revision: 2,
    status,
    stored_status: status,
    valid_until: "2026-09-01T18:00:00Z",
    currency: "USD",
    subtotal: "500.00",
    discount_total: "0.00",
    total: "500.00",
    notes: "",
    lines: [
      {
        id: "line-1",
        description: "Alquiler del salón",
        unit_label: "evento",
        quantity: "1.000",
        unit_price: "500.00",
        discount_amount: "0.00",
        line_subtotal: "500.00",
        line_total: "500.00",
      },
    ],
    reservation_id: null,
  };
}

function quotation(current: QuotationVersion): Quotation {
  return {
    id: "quotation-1",
    event_request_id: "request-1",
    visible_number: "COT-2026-000001",
    versions: [current],
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("edición, emisión y aceptación de cotizaciones", () => {
  it("guarda el borrador y emite la versión vigente", async () => {
    const onChanged = vi.fn(() => Promise.resolve());
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = requestUrl(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QuoteEditor
        organizationId="org-1"
        request={request}
        quotation={quotation(version("draft"))}
        canManage
        onChanged={onChanged}
      />,
    );
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Salón con mobiliario" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar borrador" }));
    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledTimes(1);
    });
    const saveCall = fetchMock.mock.calls.find(
      ([input, init]) => requestUrl(input).endsWith("/versions/1/") && init?.method === "PUT",
    );
    expect(requestBody(saveCall?.[1])).toMatchObject({
      revision: 2,
      lines: [{ description: "Salón con mobiliario" }],
    });

    fireEvent.click(screen.getByRole("button", { name: "Emitir cotización" }));
    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledTimes(2);
    });
    expect(
      fetchMock.mock.calls.some(([input]) => requestUrl(input).endsWith("/versions/1/issue/")),
    ).toBe(true);
  });

  it("acepta una versión emitida y bloquea la fecha", async () => {
    const onChanged = vi.fn(() => Promise.resolve());
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = requestUrl(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QuoteEditor
        organizationId="org-1"
        request={request}
        quotation={quotation(version("issued"))}
        canManage
        onChanged={onChanged}
      />,
    );
    fireEvent.change(screen.getByLabelText("Nota"), { target: { value: "Aceptada por teléfono" } });
    fireEvent.click(screen.getByRole("button", { name: "Aceptar y bloquear fecha" }));

    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledOnce();
    });
    const acceptanceCall = fetchMock.mock.calls.find(([input]) =>
      requestUrl(input).endsWith("/versions/1/accept/"),
    );
    expect(requestBody(acceptanceCall?.[1])).toEqual({
      channel: "whatsapp",
      note: "Aceptada por teléfono",
    });
  });
});
