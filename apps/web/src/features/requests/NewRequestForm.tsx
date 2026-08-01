import { useEffect, useState, type SyntheticEvent } from "react";

import { api, type EventRequest, type Person } from "../../api";
import { Notice } from "../../shared/components";
import { formText, localToInstant, message } from "../../shared/utilities";

function PersonFields({ prefix = "" }: { prefix?: string }) {
  return (
    <>
      <label>
        Nombre completo
        <input name={`${prefix}full_name`} required />
      </label>
      <label>
        Teléfono ecuatoriano
        <input name={`${prefix}phone`} inputMode="tel" placeholder="099 123 4567" required />
      </label>
      <label>
        Correo opcional
        <input name={`${prefix}email`} type="email" />
      </label>
      <label>
        Origen
        <select name={`${prefix}origin`} defaultValue="whatsapp">
          <option value="whatsapp">WhatsApp</option>
          <option value="phone_call">Llamada</option>
          <option value="social_network">Red social</option>
          <option value="referral">Referido</option>
          <option value="walk_in">Visita</option>
          <option value="website">Sitio web</option>
          <option value="other">Otro</option>
        </select>
      </label>
    </>
  );
}

export function NewRequestForm({
  organizationId,
  timeZone,
  onCreated,
  onCancel,
}: {
  organizationId: string;
  timeZone: string;
  onCreated: (request: EventRequest) => void;
  onCancel: () => void;
}) {
  const [people, setPeople] = useState<Person[]>([]);
  const [newPerson, setNewPerson] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void api<{ people: Person[] }>(`/api/v1/organizations/${organizationId}/people/`)
      .then((body) => {
        setPeople(body.people);
      })
      .catch((caught: unknown) => {
        setError(message(caught));
      });
  }, [organizationId]);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      let personId = formText(form, "person_id");
      if (newPerson) {
        const person = await api<Person>(`/api/v1/organizations/${organizationId}/people/`, {
          method: "POST",
          body: JSON.stringify({
            full_name: formText(form, "person_full_name"),
            phone: formText(form, "person_phone"),
            email: formText(form, "person_email"),
            origin: formText(form, "person_origin"),
          }),
        });
        personId = person.id;
      }
      if (!personId) throw new Error("Selecciona o registra una persona.");
      const created = await api<EventRequest>(
        `/api/v1/organizations/${organizationId}/event-requests/`,
        {
          method: "POST",
          body: JSON.stringify({
            person_id: personId,
            event_type: formText(form, "event_type"),
            starts_at: localToInstant(formText(form, "starts_at"), timeZone),
            ends_at: localToInstant(formText(form, "ends_at"), timeZone),
            estimated_guests: Number(formText(form, "estimated_guests")),
            general_need: formText(form, "general_need"),
            notes: formText(form, "notes"),
            origin: formText(form, "origin"),
          }),
        },
      );
      onCreated(created);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="new-request-title">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Nueva oportunidad</p>
          <h2 id="new-request-title">Registra una solicitud</h2>
        </div>
        <button className="button button--ghost" onClick={onCancel}>
          Cerrar
        </button>
      </header>
      {error && <Notice>{error}</Notice>}
      <form className="form-stack" onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend>Persona</legend>
          <div className="segmented">
            <button
              type="button"
              aria-pressed={!newPerson}
              onClick={() => {
                setNewPerson(false);
              }}
            >
              Seleccionar
            </button>
            <button
              type="button"
              aria-pressed={newPerson}
              onClick={() => {
                setNewPerson(true);
              }}
            >
              Registrar nueva
            </button>
          </div>
          {newPerson ? (
            <div className="form-grid">
              <PersonFields prefix="person_" />
            </div>
          ) : (
            <label>
              Persona
              <select name="person_id" required defaultValue="">
                <option value="" disabled>
                  Selecciona una persona
                </option>
                {people.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name} · {person.phone_e164}
                  </option>
                ))}
              </select>
            </label>
          )}
        </fieldset>
        <fieldset>
          <legend>Evento</legend>
          <div className="form-grid">
            <label>
              Tipo de evento
              <input name="event_type" required />
            </label>
            <label>
              Invitados estimados
              <input name="estimated_guests" type="number" min="1" required />
            </label>
            <label>
              Inicio
              <input name="starts_at" type="datetime-local" required />
            </label>
            <label>
              Fin
              <input name="ends_at" type="datetime-local" required />
            </label>
            <label className="span-two">
              Necesidad general
              <textarea name="general_need" required rows={3} />
            </label>
            <label>
              Origen
              <select name="origin" defaultValue="whatsapp">
                <option value="whatsapp">WhatsApp</option>
                <option value="phone_call">Llamada</option>
                <option value="social_network">Red social</option>
                <option value="referral">Referido</option>
                <option value="walk_in">Visita</option>
                <option value="website">Sitio web</option>
                <option value="other">Otro</option>
              </select>
            </label>
            <label className="span-two">
              Notas
              <textarea name="notes" rows={3} />
            </label>
          </div>
        </fieldset>
        <div className="form-actions">
          <button type="button" className="button button--secondary" onClick={onCancel}>
            Cancelar
          </button>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Guardando…" : "Crear solicitud"}
          </button>
        </div>
      </form>
    </section>
  );
}
