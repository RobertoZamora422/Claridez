import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EventRequest } from "../../api";
import { NewRequestForm } from "./NewRequestForm";

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

const createdRequest = {
  id: "request-1",
  person: { id: "person-1", full_name: "María Torres", commercial_type: "lead", revision: 1 },
  event_type_id: "event-type-1",
  event_type: "Boda",
  venue: { id: "venue-1", name: "Sede principal" },
  space: { id: "space-1", name: "Espacio principal" },
  starts_at: "2026-09-12T20:00:00Z",
  ends_at: "2026-09-13T02:00:00Z",
  event_timezone: "America/Guayaquil",
  estimated_guests: 120,
  general_need: "Salón y mobiliario",
  notes: "",
  origin: "whatsapp",
  status: "new",
  revision: 1,
  quotation_id: null,
  reservation: null,
} satisfies EventRequest;

function completeEventFields(): void {
  fireEvent.change(screen.getByLabelText("Tipo de evento"), {
    target: { value: "event-type-1" },
  });
  fireEvent.change(screen.getByLabelText("Espacio"), { target: { value: "space-1" } });
  fireEvent.change(screen.getByLabelText("Invitados estimados"), { target: { value: "120" } });
  fireEvent.change(screen.getByLabelText("Inicio"), { target: { value: "2026-09-12T15:00" } });
  fireEvent.change(screen.getByLabelText("Fin"), { target: { value: "2026-09-12T21:00" } });
  fireEvent.change(screen.getByLabelText("Necesidad general"), {
    target: { value: "Salón y mobiliario" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("persona inline de una solicitud", () => {
  it("crea la solicitud con una persona existente", async () => {
    const onCreated = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = requestUrl(input);
      if (url.endsWith("/people/"))
        return Promise.resolve(
          json({
            people: [
              {
                id: "person-1",
                full_name: "María Torres",
                phone_e164: "+593991234567",
                commercial_type: "lead",
                revision: 1,
              },
            ],
          }),
        );
      if (url.endsWith("/event-types/"))
        return Promise.resolve(
          json({ event_types: [{ id: "event-type-1", name: "Boda", is_active: true }] }),
        );
      if (url.endsWith("/venues/"))
        return Promise.resolve(
          json({
            venues: [
              {
                id: "venue-1",
                name: "Sede principal",
                is_active: true,
                spaces: [{ id: "space-1", name: "Espacio principal", is_active: true }],
              },
            ],
          }),
        );
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/event-requests/")) return Promise.resolve(json(createdRequest));
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <NewRequestForm
        organizationId="org-1"
        timeZone="America/Guayaquil"
        onCreated={onCreated}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.change(await screen.findByLabelText("Persona"), { target: { value: "person-1" } });
    completeEventFields();
    fireEvent.click(screen.getByRole("button", { name: "Crear solicitud" }));

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(createdRequest);
    });
    const requestCall = fetchMock.mock.calls.find(([input]) =>
      requestUrl(input).endsWith("/event-requests/"),
    );
    expect(requestBody(requestCall?.[1])).toMatchObject({
      person_id: "person-1",
      event_type_id: "event-type-1",
      space_id: "space-1",
    });
  });

  it("registra una persona nueva antes de crear la solicitud", async () => {
    const onCreated = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url === "/api/v1/auth/csrf/") return Promise.resolve(json({ csrf_token: "csrf" }));
      if (url.endsWith("/people/") && init?.method === "POST")
        return Promise.resolve(
          json({
            id: "person-2",
            full_name: "Luis Pérez",
            phone_e164: "+593981234567",
            commercial_type: "lead",
            revision: 1,
          }),
        );
      if (url.endsWith("/people/")) return Promise.resolve(json({ people: [] }));
      if (url.endsWith("/event-types/"))
        return Promise.resolve(
          json({ event_types: [{ id: "event-type-1", name: "Boda", is_active: true }] }),
        );
      if (url.endsWith("/venues/"))
        return Promise.resolve(
          json({
            venues: [
              {
                id: "venue-1",
                name: "Sede principal",
                is_active: true,
                spaces: [{ id: "space-1", name: "Espacio principal", is_active: true }],
              },
            ],
          }),
        );
      if (url.endsWith("/event-requests/")) return Promise.resolve(json(createdRequest));
      return Promise.resolve(json({ error: { code: "unexpected" } }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <NewRequestForm
        organizationId="org-1"
        timeZone="America/Guayaquil"
        onCreated={onCreated}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Registrar nueva" }));
    fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Luis Pérez" } });
    fireEvent.change(screen.getByLabelText("Teléfono ecuatoriano"), {
      target: { value: "098 123 4567" },
    });
    completeEventFields();
    fireEvent.click(screen.getByRole("button", { name: "Crear solicitud" }));

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(createdRequest);
    });
    const personCall = fetchMock.mock.calls.find(
      ([input, init]) => requestUrl(input).endsWith("/people/") && init?.method === "POST",
    );
    expect(requestBody(personCall?.[1])).toMatchObject({
      full_name: "Luis Pérez",
      phone: "098 123 4567",
    });
    const requestCall = fetchMock.mock.calls.find(([input]) =>
      requestUrl(input).endsWith("/event-requests/"),
    );
    expect(requestBody(requestCall?.[1])).toMatchObject({ person_id: "person-2" });
  });
});
