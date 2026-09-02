import { useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { p14ExternalApi } from "../../api";
import { BrandLogo } from "../../Brand";
import { Loading, Notice } from "../../shared/components";
import { message } from "../../shared/utilities";
import { AntiAbuse } from "./AntiAbuse";

interface Option {
  id: string;
  revision: number;
  label: string;
}
interface Location {
  venue_id: string;
  venue_revision: number;
  venue_label: string;
  space_id: string;
  space_revision: number;
  space_label: string;
}
interface Consent {
  purpose: string;
  channel: string;
  text: string;
  text_sha256: string;
  version: string;
  required: boolean;
}
interface PublicForm {
  organization: string;
  title: string;
  introduction: string;
  event_types: Option[];
  locations: Location[];
  durations_minutes: number[];
  timezone: string;
  consents: Consent[];
  version: number;
}

function localValue(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

const DEFAULT_START = (() => {
  const value = new Date(Date.now() + 14 * 86_400_000);
  value.setMinutes(0, 0, 0);
  return localValue(value);
})();

export function PublicFormView({ locator }: { locator: string }) {
  const [form, setForm] = useState<PublicForm | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [antiabuseToken, setAntiabuseToken] = useState("");
  const [antiabuseReset, setAntiabuseReset] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [availability, setAvailability] = useState<boolean | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [values, setValues] = useState({
    full_name: "",
    phone: "",
    email: "",
    event_type_id: "",
    space_id: "",
    starts_at: DEFAULT_START,
    duration: "",
    estimated_guests: "",
    general_need: "",
    notes: "",
  });
  const [consents, setConsents] = useState<Record<string, boolean>>({});

  useEffect(() => {
    void p14ExternalApi<PublicForm>(`/api/v1/public/forms/${encodeURIComponent(locator)}/`)
      .then((body) => {
        setForm(body);
        setValues((current) => ({
          ...current,
          event_type_id: body.event_types[0]?.id ?? "",
          space_id: body.locations[0]?.space_id ?? "",
          duration: String(body.durations_minutes[0] ?? ""),
        }));
      })
      .catch((caught: unknown) => {
        setLoadError(message(caught));
      });
  }, [locator]);

  if (loadError)
    return (
      <main className="external-surface">
        <BrandLogo />
        <Notice>{loadError}</Notice>
      </main>
    );
  if (!form)
    return (
      <main className="external-surface">
        <Loading label="Preparando el formulario…" />
      </main>
    );

  const interval = {
    event_type_id: values.event_type_id,
    space_id: values.space_id,
    starts_at_local: values.starts_at,
    duration_minutes: Number(values.duration),
  };

  async function checkAvailability() {
    setError("");
    try {
      const body = await p14ExternalApi<{ available: boolean }>(
        `/api/v1/public/forms/${encodeURIComponent(locator)}/availability/`,
        { method: "POST", body: JSON.stringify(interval) },
      );
      setAvailability(body.available);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!antiabuseToken) {
      setError("Completa la protección antiabuso antes de enviar.");
      return;
    }
    setSubmitting(true);
    try {
      const body = await p14ExternalApi<{
        event_request_id: string;
        availability: boolean;
      }>(`/api/v1/public/forms/${encodeURIComponent(locator)}/`, {
        method: "POST",
        body: JSON.stringify({
          ...interval,
          idempotency_key: idempotencyKey,
          full_name: values.full_name,
          phone: values.phone,
          email: values.email,
          estimated_guests: Number(values.estimated_guests),
          general_need: values.general_need,
          notes: values.notes,
          consents,
          attribution: {
            referrer: document.referrer ? new URL(document.referrer).origin : "direct",
          },
          antiabuse_token: antiabuseToken,
          antiabuse_hostname: window.location.hostname,
        }),
      });
      setAvailability(body.availability);
      setNotice(
        body.availability
          ? "Recibimos tu solicitud. El equipo comercial confirmará los siguientes pasos."
          : "Recibimos tu solicitud. El horario requiere revisión y el equipo propondrá alternativas si hace falta.",
      );
    } catch (caught: unknown) {
      setError(message(caught));
      setAntiabuseReset((current) => current + 1);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="external-surface public-capture">
      <header className="external-heading">
        <BrandLogo />
        <span>{form.organization}</span>
      </header>
      <section className="external-card" aria-labelledby="public-form-title">
        <div>
          <p className="eyebrow">Solicitud de evento</p>
          <h1 id="public-form-title">{form.title}</h1>
          <p>{form.introduction}</p>
        </div>
        {notice ? (
          <div className="success-panel" role="status">
            <h2>Solicitud registrada</h2>
            <p>{notice}</p>
            <a className="button" href={`/portal?form=${encodeURIComponent(locator)}`}>
              Acceder al portal del cliente
            </a>
          </div>
        ) : (
          <form className="structured-form" onSubmit={(event) => void submit(event)}>
            <fieldset>
              <legend>Datos de contacto</legend>
              <label>
                Nombre completo
                <input
                  required
                  autoComplete="name"
                  value={values.full_name}
                  onChange={(event) => {
                    setValues({ ...values, full_name: event.target.value });
                  }}
                />
              </label>
              <div className="form-grid">
                <label>
                  Teléfono
                  <input
                    required
                    inputMode="tel"
                    autoComplete="tel"
                    value={values.phone}
                    onChange={(event) => {
                      setValues({ ...values, phone: event.target.value });
                    }}
                  />
                </label>
                <label>
                  Correo
                  <input
                    type="email"
                    autoComplete="email"
                    value={values.email}
                    onChange={(event) => {
                      setValues({ ...values, email: event.target.value });
                    }}
                  />
                </label>
              </div>
            </fieldset>
            <fieldset>
              <legend>Evento deseado</legend>
              <div className="form-grid">
                <label>
                  Tipo de evento
                  <select
                    required
                    value={values.event_type_id}
                    onChange={(event) => {
                      setValues({ ...values, event_type_id: event.target.value });
                    }}
                  >
                    {form.event_types.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Sede y espacio
                  <select
                    required
                    value={values.space_id}
                    onChange={(event) => {
                      setValues({ ...values, space_id: event.target.value });
                    }}
                  >
                    {form.locations.map((option) => (
                      <option key={option.space_id} value={option.space_id}>
                        {option.venue_label} · {option.space_label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Fecha y hora
                  <input
                    required
                    type="datetime-local"
                    value={values.starts_at}
                    onChange={(event) => {
                      setValues({ ...values, starts_at: event.target.value });
                    }}
                  />
                  <small>Zona: {form.timezone}</small>
                </label>
                <label>
                  Duración
                  <select
                    required
                    value={values.duration}
                    onChange={(event) => {
                      setValues({ ...values, duration: event.target.value });
                    }}
                  >
                    {form.durations_minutes.map((minutes) => (
                      <option key={minutes} value={minutes}>
                        {minutes} minutos
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Invitados estimados
                  <input
                    required
                    min="1"
                    type="number"
                    value={values.estimated_guests}
                    onChange={(event) => {
                      setValues({ ...values, estimated_guests: event.target.value });
                    }}
                  />
                </label>
              </div>
              <button
                className="button button--ghost"
                type="button"
                onClick={() => void checkAvailability()}
              >
                Consultar disponibilidad informativa
              </button>
              {availability !== null ? (
                <p className="availability-note" role="status">
                  {availability
                    ? "El intervalo aparece disponible ahora; la disponibilidad se confirmará después."
                    : "El intervalo aparece ocupado; puedes enviar la solicitud y el equipo revisará alternativas."}
                </p>
              ) : null}
              <label>
                ¿Qué necesitas?
                <textarea
                  required
                  rows={4}
                  value={values.general_need}
                  onChange={(event) => {
                    setValues({ ...values, general_need: event.target.value });
                  }}
                />
              </label>
              <label>
                Notas adicionales
                <textarea
                  rows={3}
                  value={values.notes}
                  onChange={(event) => {
                    setValues({ ...values, notes: event.target.value });
                  }}
                />
              </label>
            </fieldset>
            {form.consents.length ? (
              <fieldset>
                <legend>Preferencias y consentimiento</legend>
                {form.consents.map((consent) => {
                  const key = `${consent.purpose}:${consent.channel}`;
                  return (
                    <label className="check-row" key={key}>
                      <input
                        type="checkbox"
                        required={consent.required}
                        checked={Boolean(consents[key])}
                        onChange={(event) => {
                          setConsents({ ...consents, [key]: event.target.checked });
                        }}
                      />
                      <span>{consent.text}</span>
                    </label>
                  );
                })}
              </fieldset>
            ) : null}
            <AntiAbuse
              action="public_form_submit"
              resetKey={antiabuseReset}
              onToken={setAntiabuseToken}
            />
            {error ? <Notice>{error}</Notice> : null}
            <button className="button" type="submit" disabled={submitting || !antiabuseToken}>
              {submitting ? "Enviando…" : "Enviar solicitud"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
