import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from "react";

import {
  ApiError,
  api,
  login,
  logout,
  type Availability,
  type EventRequest,
  type Organization,
  type Person,
  type Quotation,
  type QuotationLine,
  type Reservation,
  type User,
} from "./api";
import { BrandLogo, BrandSymbol } from "./Brand";
import "./styles.css";

const STATUS_LABELS: Record<string, string> = {
  new: "Nueva",
  quoted: "Cotizada",
  accepted: "Aceptada",
  confirmed: "Confirmada",
  closed_lost: "Oportunidad perdida",
  cancelled: "Cancelada",
  provisional: "Reserva provisional",
  expired: "Vencida",
  draft: "Borrador",
  issued: "Emitida",
  superseded: "Sustituida",
  withdrawn: "Retirada",
};

type Page = "agenda" | "requests";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "No fue posible completar la operación.";
}

function formatDate(value: string, timeZone: string, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("es-EC", {
    timeZone,
    ...(options ?? { dateStyle: "medium", timeStyle: "short" }),
  }).format(new Date(value));
}

function toInputDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${String(year)}-${month}-${day}`;
}

function localToInstant(value: string, timeZone: string): string {
  const [datePart, timePart = "00:00"] = value.split("T");
  if (datePart === undefined) throw new Error("Fecha inválida");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    hour === undefined ||
    minute === undefined ||
    [year, month, day, hour, minute].some(Number.isNaN)
  ) {
    throw new Error("Fecha inválida");
  }
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(guess)).map((part) => [part.type, part.value]),
  );
  const rendered = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );
  return new Date(guess - (rendered - guess)).toISOString();
}

function formText(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

function useInitialLoad(load: () => Promise<void>): void {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [load]);
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`status status--${value}`}>{STATUS_LABELS[value] ?? value}</span>;
}

function Notice({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "info" }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

function Loading({ label = "Cargando información…" }: { label?: string }) {
  return (
    <p className="loading" role="status">
      {label}
    </p>
  );
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [resetMode, setResetMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    try {
      if (resetMode) {
        await api("/api/v1/auth/password/reset/request/", {
          method: "POST",
          body: JSON.stringify({ email }),
        });
        setInfo("Si la cuenta está disponible, recibirás las instrucciones de recuperación.");
      } else {
        onAuthenticated(await login(email, password));
      }
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-brand" aria-labelledby="brand-title">
        <BrandSymbol />
        <p className="eyebrow">Centro de control para salones de eventos</p>
        <h1 id="brand-title">Todo tu negocio, claro y bajo control.</h1>
        <p>
          Convierte consultas en reservas confirmadas con una agenda confiable y un historial
          comercial preciso.
        </p>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <BrandLogo />
        <h2 id="auth-title">{resetMode ? "Recupera tu acceso" : "Ingresa a tu organización"}</h2>
        <p className="muted">
          {resetMode
            ? "Te enviaremos un enlace si la cuenta existe."
            : "Usa tu cuenta de trabajo para continuar."}
        </p>
        {error && <Notice>{error}</Notice>}
        {info && <Notice tone="info">{info}</Notice>}
        <form onSubmit={(event) => void submit(event)} className="form-stack">
          <label>
            Correo electrónico
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </label>
          {!resetMode && (
            <label>
              Contraseña
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
            </label>
          )}
          <button className="button button--primary" disabled={busy}>
            {busy ? "Procesando…" : resetMode ? "Solicitar recuperación" : "Ingresar"}
          </button>
        </form>
        <button
          className="button button--ghost"
          onClick={() => {
            setResetMode((value) => !value);
            setError("");
            setInfo("");
          }}
        >
          {resetMode ? "Volver al ingreso" : "Olvidé mi contraseña"}
        </button>
      </section>
    </main>
  );
}

function OrganizationPicker({
  organizations,
  onSelect,
}: {
  organizations: Organization[];
  onSelect: (organization: Organization) => Promise<void>;
}) {
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  return (
    <main className="center-layout">
      <section className="picker-card" aria-labelledby="organization-title">
        <BrandLogo />
        <h1 id="organization-title">Elige una organización</h1>
        <p className="muted">El contexto seleccionado define los datos que puedes consultar.</p>
        {error && <Notice>{error}</Notice>}
        {organizations.length === 0 ? (
          <Notice tone="info">Tu cuenta no tiene organizaciones activas.</Notice>
        ) : (
          <div className="organization-list">
            {organizations.map((organization) => (
              <button
                key={organization.id}
                className="organization-option"
                disabled={busyId !== ""}
                onClick={() => {
                  setBusyId(organization.id);
                  setError("");
                  void onSelect(organization).catch((caught: unknown) => {
                    setError(message(caught));
                    setBusyId("");
                  });
                }}
              >
                <span className="organization-avatar" aria-hidden="true">
                  {organization.name.slice(0, 1).toUpperCase()}
                </span>
                <span>
                  <strong>{organization.name}</strong>
                  <small>
                    {busyId === organization.id ? "Abriendo…" : "Abrir centro de control"}
                  </small>
                </span>
                <span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function AgendaView({ organizationId, timeZone }: { organizationId: string; timeZone: string }) {
  const [startDate, setStartDate] = useState(toInputDate(new Date()));
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const from = localToInstant(`${startDate}T00:00`, timeZone);
      const toDate = new Date(from);
      toDate.setUTCDate(toDate.getUTCDate() + 7);
      const params = new URLSearchParams({ from, to: toDate.toISOString() });
      setAvailability(
        await api<Availability>(`/api/v1/organizations/${organizationId}/availability/?${params}`),
      );
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId, startDate, timeZone]);

  useInitialLoad(load);

  return (
    <section aria-labelledby="agenda-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Próximos 7 días</p>
          <h1 id="agenda-title">Agenda y disponibilidad</h1>
          <p className="muted">Horarios bloqueados en {timeZone}.</p>
        </div>
        <label className="date-control">
          Semana desde
          <input
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
            }}
          />
        </label>
      </header>
      {error && <Notice>{error}</Notice>}
      {loading ? (
        <Loading />
      ) : availability?.blocks.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">
            ✓
          </div>
          <h2>Semana disponible</h2>
          <p>No hay reservas provisionales o confirmadas en este periodo.</p>
        </div>
      ) : (
        <div className="agenda-grid">
          {availability?.blocks.map((block) => (
            <article className="event-card" key={block.id}>
              <div>
                <p className="event-date">
                  {formatDate(block.starts_at, timeZone, {
                    weekday: "long",
                    day: "numeric",
                    month: "long",
                  })}
                </p>
                <h2>{block.event_type ?? "Evento reservado"}</h2>
              </div>
              <StatusBadge value={block.status} />
              <dl>
                <div>
                  <dt>Inicio</dt>
                  <dd>{formatDate(block.starts_at, timeZone)}</dd>
                </div>
                <div>
                  <dt>Fin</dt>
                  <dd>{formatDate(block.ends_at, timeZone)}</dd>
                </div>
                {block.status === "provisional" && (
                  <div>
                    <dt>Vence</dt>
                    <dd>{formatDate(block.hold_expires_at, timeZone)}</dd>
                  </div>
                )}
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

interface RequestListProps {
  organizationId: string;
  timeZone: string;
  canManage: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

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

function NewRequestForm({
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

function QuoteEditor({
  organizationId,
  request,
  quotation,
  canManage,
  onChanged,
}: {
  organizationId: string;
  request: EventRequest;
  quotation: Quotation | null;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const latest = quotation?.versions.at(-1) ?? null;
  const [lines, setLines] = useState<QuotationLine[]>(
    latest?.lines ?? [
      {
        description: "",
        unit_label: "evento",
        quantity: "1.000",
        unit_price: "0.00",
        discount_amount: "0.00",
      },
    ],
  );
  const defaultValidity = useMemo(() => {
    const date = new Date();
    date.setDate(date.getDate() + 3);
    return date.toISOString().slice(0, 16);
  }, []);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await operation();
      await onChanged();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }
  async function createQuote() {
    await action(() =>
      api(`/api/v1/organizations/${organizationId}/event-requests/${request.id}/quotations/`, {
        method: "POST",
        body: JSON.stringify({ valid_until: new Date(defaultValidity).toISOString() }),
      }),
    );
  }
  async function createVersion() {
    if (!quotation) return;
    await action(() =>
      api(`/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/`, {
        method: "POST",
        body: JSON.stringify({ valid_until: new Date(defaultValidity).toISOString() }),
      }),
    );
  }
  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!quotation || !latest) return;
    const form = new FormData(event.currentTarget);
    await action(() =>
      api(
        `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/`,
        {
          method: "PUT",
          body: JSON.stringify({
            revision: latest.revision,
            valid_until: new Date(formText(form, "valid_until")).toISOString(),
            notes: formText(form, "notes"),
            lines,
          }),
        },
      ),
    );
  }
  function updateLine(index: number, field: keyof QuotationLine, value: string) {
    setLines((current) =>
      current.map((line, position) => (position === index ? { ...line, [field]: value } : line)),
    );
  }

  if (!quotation)
    return (
      <section className="panel">
        <h2>Cotización</h2>
        <p className="muted">Prepara una propuesta con precios y vigencia.</p>
        {error && <Notice>{error}</Notice>}
        {canManage && (
          <button
            className="button button--primary"
            disabled={busy}
            onClick={() => void createQuote()}
          >
            Crear cotización
          </button>
        )}
      </section>
    );
  return (
    <section className="panel" aria-labelledby="quote-title">
      <header className="panel-header">
        <div>
          <p className="eyebrow">{quotation.visible_number}</p>
          <h2 id="quote-title">Cotización · versión {latest?.version}</h2>
        </div>
        {latest && <StatusBadge value={latest.status} />}
      </header>
      {error && <Notice>{error}</Notice>}
      {latest?.stored_status === "draft" && canManage ? (
        <form className="form-stack" onSubmit={(event) => void save(event)}>
          <div className="form-grid">
            <label>
              Vigencia
              <input
                name="valid_until"
                type="datetime-local"
                defaultValue={latest.valid_until.slice(0, 16)}
                required
              />
            </label>
            <label className="span-two">
              Notas
              <textarea name="notes" defaultValue={latest.notes} rows={2} />
            </label>
          </div>
          <div className="line-list">
            <div className="line-header">
              <h3>Líneas</h3>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => {
                  setLines((current) => [
                    ...current,
                    {
                      description: "",
                      unit_label: "unidad",
                      quantity: "1.000",
                      unit_price: "0.00",
                      discount_amount: "0.00",
                    },
                  ]);
                }}
              >
                Añadir línea
              </button>
            </div>
            {lines.map((line, index) => (
              <div className="quote-line" key={line.id ?? index}>
                <label>
                  Descripción
                  <input
                    required
                    value={line.description}
                    onChange={(event) => {
                      updateLine(index, "description", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Cantidad
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    required
                    value={line.quantity}
                    onChange={(event) => {
                      updateLine(index, "quantity", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Precio USD
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={line.unit_price}
                    onChange={(event) => {
                      updateLine(index, "unit_price", event.target.value);
                    }}
                  />
                </label>
                <label>
                  Descuento USD
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={line.discount_amount}
                    onChange={(event) => {
                      updateLine(index, "discount_amount", event.target.value);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Eliminar línea ${String(index + 1)}`}
                  disabled={lines.length === 1}
                  onClick={() => {
                    setLines((current) => current.filter((_, position) => position !== index));
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button className="button button--secondary" disabled={busy}>
              Guardar borrador
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={busy || latest.lines.length === 0}
              onClick={() =>
                void action(() =>
                  api(
                    `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/issue/`,
                    { method: "POST", body: "{}" },
                  ),
                )
              }
            >
              Emitir cotización
            </button>
          </div>
        </form>
      ) : (
        latest && (
          <div>
            <div className="money-summary">
              <div>
                <span>Subtotal</span>
                <strong>${latest.subtotal}</strong>
              </div>
              <div>
                <span>Descuentos</span>
                <strong>− ${latest.discount_total}</strong>
              </div>
              <div className="money-total">
                <span>Total</span>
                <strong>${latest.total} USD</strong>
              </div>
            </div>
            {canManage &&
              (request.status === "new" || request.status === "quoted") &&
              latest.status !== "draft" && (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() => {
                    void createVersion();
                  }}
                >
                  Crear nueva versión
                </button>
              )}
            {latest.status === "issued" && canManage && (
              <AcceptanceForm
                busy={busy}
                onAccept={(channel, note) =>
                  action(() =>
                    api(
                      `/api/v1/organizations/${organizationId}/quotations/${quotation.id}/versions/${String(latest.version)}/accept/`,
                      { method: "POST", body: JSON.stringify({ channel, note }) },
                    ),
                  )
                }
              />
            )}
          </div>
        )
      )}
    </section>
  );
}

function AcceptanceForm({
  busy,
  onAccept,
}: {
  busy: boolean;
  onAccept: (channel: string, note: string) => Promise<void>;
}) {
  return (
    <form
      className="command-box"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        void onAccept(formText(form, "channel"), formText(form, "note"));
      }}
    >
      <h3>Registrar aceptación</h3>
      <p>Esta acción crea una reserva provisional por 48 horas.</p>
      <div className="form-grid">
        <label>
          Canal
          <select name="channel" defaultValue="whatsapp">
            <option value="whatsapp">WhatsApp</option>
            <option value="phone_call">Llamada</option>
            <option value="email">Correo</option>
            <option value="in_person">Presencial</option>
            <option value="other">Otro</option>
          </select>
        </label>
        <label>
          Nota
          <input name="note" />
        </label>
      </div>
      <button className="button button--primary" disabled={busy}>
        Aceptar y bloquear fecha
      </button>
    </form>
  );
}

function ReservationActions({
  organizationId,
  reservation,
  capabilities,
  onChanged,
}: {
  organizationId: string;
  reservation: Reservation;
  capabilities: Set<string>;
  onChanged: () => Promise<void>;
}) {
  const [kind, setKind] = useState<"external_deposit" | "waiver">("external_deposit");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(operation: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await operation();
      await onChanged();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" aria-labelledby="reservation-title">
      <header className="panel-header">
        <div>
          <p className="eyebrow">Control de agenda</p>
          <h2 id="reservation-title">Reserva</h2>
        </div>
        <StatusBadge value={reservation.status} />
      </header>
      {error && <Notice>{error}</Notice>}
      {reservation.status === "provisional" && capabilities.has("reservation:confirm") && (
        <form
          className="command-box"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void run(() =>
              api(
                `/api/v1/organizations/${organizationId}/reservations/${reservation.id}/confirm/`,
                {
                  method: "POST",
                  body: JSON.stringify(
                    kind === "external_deposit"
                      ? {
                          kind,
                          recognized_amount: formText(form, "recognized_amount"),
                          reported_at: new Date(formText(form, "reported_at")).toISOString(),
                          reference: formText(form, "reference"),
                        }
                      : { kind, waiver_reason: formText(form, "waiver_reason") },
                  ),
                },
              ),
            );
          }}
        >
          <h3>Confirmar reserva</h3>
          <p>Claridez registra una constancia operativa; no procesa el pago.</p>
          {capabilities.has("reservation:waive_deposit") && (
            <div className="segmented">
              <button
                type="button"
                aria-pressed={kind === "external_deposit"}
                onClick={() => {
                  setKind("external_deposit");
                }}
              >
                Anticipo externo
              </button>
              <button
                type="button"
                aria-pressed={kind === "waiver"}
                onClick={() => {
                  setKind("waiver");
                }}
              >
                Excepción
              </button>
            </div>
          )}
          {kind === "external_deposit" ? (
            <div className="form-grid">
              <label>
                Monto reconocido USD
                <input name="recognized_amount" type="number" min="0.01" step="0.01" required />
              </label>
              <label>
                Fecha y hora informada
                <input name="reported_at" type="datetime-local" required />
              </label>
              <label className="span-two">
                Referencia o nota
                <input name="reference" required />
              </label>
            </div>
          ) : (
            <label>
              Razón de la excepción
              <textarea name="waiver_reason" required rows={3} />
            </label>
          )}
          <button className="button button--primary" disabled={busy}>
            Confirmar reserva
          </button>
        </form>
      )}
      {reservation.confirmed_at && (
        <div className="evidence">
          <h3>
            {reservation.confirmation_kind === "waiver"
              ? "Excepción autorizada"
              : "Anticipo reconocido externamente"}
          </h3>
          {reservation.recognized_deposit_amount && (
            <p>
              <strong>${reservation.recognized_deposit_amount} USD</strong> · No procesado por
              Claridez
            </p>
          )}
          <p>{reservation.deposit_reference ?? reservation.waiver_reason}</p>
        </div>
      )}
      {["provisional", "confirmed"].includes(reservation.status) &&
        capabilities.has("reservation:cancel") && (
          <form
            className="danger-zone"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void run(() =>
                api(
                  `/api/v1/organizations/${organizationId}/reservations/${reservation.id}/cancel/`,
                  { method: "POST", body: JSON.stringify({ reason: formText(form, "reason") }) },
                ),
              );
            }}
          >
            <label>
              Razón de cancelación
              <input name="reason" required />
            </label>
            <button className="button button--danger" disabled={busy}>
              Cancelar reserva
            </button>
          </form>
        )}
    </section>
  );
}

function CloseLostAction({
  organizationId,
  requestId,
  onChanged,
}: {
  organizationId: string;
  requestId: string;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <section className="panel">
      <h2>Cerrar oportunidad</h2>
      <p className="muted">Úsalo únicamente si la reserva nunca llegó a confirmarse.</p>
      {error && <Notice>{error}</Notice>}
      <form
        className="danger-zone"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError("");
          void api(`/api/v1/organizations/${organizationId}/event-requests/${requestId}/close/`, {
            method: "POST",
            body: JSON.stringify({ reason: formText(form, "reason") }),
          })
            .then(onChanged)
            .catch((caught: unknown) => {
              setError(message(caught));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
      >
        <label>
          Razón de pérdida
          <input name="reason" required />
        </label>
        <button className="button button--danger" disabled={busy}>
          Marcar como oportunidad perdida
        </button>
      </form>
    </section>
  );
}

function RequestDetail({
  organizationId,
  requestId,
  timeZone,
  capabilities,
  onBack,
}: {
  organizationId: string;
  requestId: string;
  timeZone: string;
  capabilities: Set<string>;
  onBack: () => void;
}) {
  const [request, setRequest] = useState<EventRequest | null>(null);
  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const current = await api<EventRequest>(
        `/api/v1/organizations/${organizationId}/event-requests/${requestId}/`,
      );
      setRequest(current);
      const quote = current.quotation_id
        ? await api<Quotation>(
            `/api/v1/organizations/${organizationId}/quotations/${current.quotation_id}/`,
          )
        : null;
      setQuotation(quote);
      const reservationId = [...(quote?.versions ?? [])]
        .reverse()
        .find((version) => version.reservation_id)?.reservation_id;
      setReservation(
        reservationId
          ? await api<Reservation>(
              `/api/v1/organizations/${organizationId}/reservations/${reservationId}/`,
            )
          : null,
      );
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId, requestId]);
  useInitialLoad(load);
  if (loading) return <Loading />;
  if (error || !request)
    return (
      <>
        <Notice>{error || "La solicitud no está disponible."}</Notice>
        <button className="button button--secondary" onClick={onBack}>
          Volver
        </button>
      </>
    );
  const latestQuote = quotation?.versions.at(-1);
  const quoteEditorKey = latestQuote
    ? `${latestQuote.id}:${String(latestQuote.version)}:${String(latestQuote.revision)}:${latestQuote.status}`
    : "no-quotation";
  return (
    <section>
      <button className="back-link" onClick={onBack}>
        ← Volver a solicitudes
      </button>
      <header className="page-header">
        <div>
          <p className="eyebrow">Detalle comercial</p>
          <h1>{request.event_type}</h1>
          <p className="muted">
            {request.person.full_name ?? "Contacto restringido"} ·{" "}
            {formatDate(request.starts_at, timeZone)}
          </p>
        </div>
        <StatusBadge value={request.status} />
      </header>
      <div className="detail-grid">
        <article className="panel">
          <h2>Solicitud</h2>
          <dl className="details">
            <div>
              <dt>Horario</dt>
              <dd>
                {formatDate(request.starts_at, timeZone)} — {formatDate(request.ends_at, timeZone)}
              </dd>
            </div>
            <div>
              <dt>Invitados</dt>
              <dd>{request.estimated_guests}</dd>
            </div>
            <div>
              <dt>Necesidad</dt>
              <dd>{request.general_need}</dd>
            </div>
            <div>
              <dt>Origen</dt>
              <dd>{request.origin}</dd>
            </div>
          </dl>
        </article>
        <article className="panel">
          <h2>Persona</h2>
          {request.person.full_name ? (
            <dl className="details">
              <div>
                <dt>Nombre</dt>
                <dd>{request.person.full_name}</dd>
              </div>
              <div>
                <dt>Teléfono</dt>
                <dd>{request.person.phone_e164}</dd>
              </div>
              <div>
                <dt>Tipo</dt>
                <dd>{request.person.commercial_type === "client" ? "Cliente" : "Interesado"}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">No tienes capacidad para consultar datos de contacto.</p>
          )}
        </article>
      </div>
      <QuoteEditor
        key={quoteEditorKey}
        organizationId={organizationId}
        request={request}
        quotation={quotation}
        canManage={capabilities.has("sales:manage")}
        onChanged={load}
      />
      {reservation && (
        <ReservationActions
          organizationId={organizationId}
          reservation={reservation}
          capabilities={capabilities}
          onChanged={load}
        />
      )}
      {(request.status === "new" || request.status === "quoted") &&
        capabilities.has("sales:manage") && (
          <CloseLostAction
            organizationId={organizationId}
            requestId={request.id}
            onChanged={load}
          />
        )}
    </section>
  );
}

function RequestsView(props: RequestListProps & { capabilities: Set<string> }) {
  const { organizationId, timeZone, canManage, selectedId, onSelect, capabilities } = props;
  const [requests, setRequests] = useState<EventRequest[]>([]);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const body = await api<{ event_requests: EventRequest[] }>(
        `/api/v1/organizations/${organizationId}/event-requests/`,
      );
      setRequests(body.event_requests);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useInitialLoad(load);
  if (selectedId)
    return (
      <RequestDetail
        organizationId={organizationId}
        requestId={selectedId}
        timeZone={timeZone}
        capabilities={capabilities}
        onBack={() => {
          onSelect(null);
          void load();
        }}
      />
    );
  if (creating)
    return (
      <NewRequestForm
        organizationId={organizationId}
        timeZone={timeZone}
        onCancel={() => {
          setCreating(false);
        }}
        onCreated={(created) => {
          setCreating(false);
          onSelect(created.id);
        }}
      />
    );
  return (
    <section aria-labelledby="requests-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Seguimiento comercial</p>
          <h1 id="requests-title">Solicitudes</h1>
          <p className="muted">De la primera conversación a una fecha confirmada.</p>
        </div>
        {canManage && (
          <button
            className="button button--primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            Nueva solicitud
          </button>
        )}
      </header>
      {error && <Notice>{error}</Notice>}
      {loading ? (
        <Loading />
      ) : requests.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">
            ＋
          </div>
          <h2>Aún no hay solicitudes</h2>
          <p>Registra el primer interesado para comenzar el flujo comercial.</p>
          {canManage && (
            <button
              className="button button--primary"
              onClick={() => {
                setCreating(true);
              }}
            >
              Crear solicitud
            </button>
          )}
        </div>
      ) : (
        <div className="request-list">
          {requests.map((request) => (
            <button
              key={request.id}
              className="request-card"
              onClick={() => {
                onSelect(request.id);
              }}
            >
              <span>
                <strong>{request.event_type}</strong>
                <small>{request.person.full_name ?? "Contacto restringido"}</small>
              </span>
              <span>
                <small>{formatDate(request.starts_at, timeZone)}</small>
                <StatusBadge value={request.status} />
              </span>
              <span aria-hidden="true">→</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function Workspace({
  user,
  organization,
  organizations,
  onSwitch,
  onSignedOut,
}: {
  user: User;
  organization: Organization;
  organizations: Organization[];
  onSwitch: () => void;
  onSignedOut: () => void;
}) {
  const [page, setPage] = useState<Page>("agenda");
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState(new Set<string>());
  const [timeZone, setTimeZone] = useState("America/Guayaquil");
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      api<{ capabilities: string[] }>(
        `/api/v1/organizations/${organization.id}/commercial/capabilities/`,
      ),
      api<{ settings: { timezone: string } }>(`/api/v1/organizations/${organization.id}/settings/`),
    ])
      .then(([capabilityBody, settingsBody]) => {
        setCapabilities(new Set(capabilityBody.capabilities));
        setTimeZone(settingsBody.settings.timezone);
      })
      .catch((caught: unknown) => {
        setError(message(caught));
      });
  }, [organization.id]);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <BrandLogo theme="light" />
          <button className="tenant-switch" onClick={onSwitch} disabled={organizations.length < 2}>
            <span>{organization.name}</span>
            <small>
              {organizations.length > 1 ? "Cambiar organización" : "Organización activa"}
            </small>
          </button>
          <nav aria-label="Navegación principal">
            <button
              aria-current={page === "agenda" ? "page" : undefined}
              onClick={() => {
                setPage("agenda");
                setSelectedRequest(null);
              }}
            >
              <span aria-hidden="true">▦</span>Agenda
            </button>
            <button
              aria-current={page === "requests" ? "page" : undefined}
              onClick={() => {
                setPage("requests");
              }}
            >
              <span aria-hidden="true">◎</span>Solicitudes
            </button>
          </nav>
        </div>
        <div className="profile">
          <span className="profile-avatar">
            {(user.display_name || user.email).slice(0, 1).toUpperCase()}
          </span>
          <span>
            <strong>{user.display_name || user.email}</strong>
            <small>{user.email}</small>
          </span>
          <button aria-label="Cerrar sesión" onClick={() => void logout().then(onSignedOut)}>
            ↗
          </button>
        </div>
      </aside>
      <header className="mobile-header">
        <BrandLogo />
        <button className="button button--ghost" onClick={onSwitch}>
          {organization.name}
        </button>
      </header>
      <nav className="mobile-nav" aria-label="Navegación móvil">
        <button
          aria-current={page === "agenda" ? "page" : undefined}
          onClick={() => {
            setPage("agenda");
            setSelectedRequest(null);
          }}
        >
          Agenda
        </button>
        <button
          aria-current={page === "requests" ? "page" : undefined}
          onClick={() => {
            setPage("requests");
          }}
        >
          Solicitudes
        </button>
      </nav>
      <main className="workspace">
        {error && <Notice>{error}</Notice>}
        {page === "agenda" ? (
          <AgendaView organizationId={organization.id} timeZone={timeZone} />
        ) : (
          <RequestsView
            organizationId={organization.id}
            timeZone={timeZone}
            canManage={capabilities.has("sales:manage")}
            selectedId={selectedRequest}
            onSelect={setSelectedRequest}
            capabilities={capabilities}
          />
        )}
      </main>
    </div>
  );
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const loadOrganizations = useCallback(async () => {
    const [list, context] = await Promise.all([
      api<{ organizations: Organization[] }>("/api/v1/organizations/"),
      api<{ organization: Organization | null }>("/api/v1/organizations/context/"),
    ]);
    setOrganizations(list.organizations);
    setOrganization(context.organization);
  }, []);
  useEffect(() => {
    void api<{ user: User }>("/api/v1/auth/me/")
      .then(async (body) => {
        setUser(body.user);
        await loadOrganizations();
      })
      .catch((caught: unknown) => {
        if (!(caught instanceof ApiError) || caught.status !== 401) setError(message(caught));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [loadOrganizations]);
  async function selectOrganization(selected: Organization) {
    const body = await api<{ organization: Organization }>("/api/v1/organizations/context/", {
      method: "POST",
      body: JSON.stringify({ organization_id: selected.id }),
    });
    setOrganization(body.organization);
  }
  if (loading)
    return (
      <main className="center-layout">
        <Loading label="Preparando Claridez…" />
      </main>
    );
  if (!user)
    return (
      <LoginScreen
        onAuthenticated={(authenticated) => {
          setUser(authenticated);
          setLoading(true);
          void loadOrganizations()
            .catch((caught: unknown) => {
              setError(message(caught));
            })
            .finally(() => {
              setLoading(false);
            });
        }}
      />
    );
  if (error)
    return (
      <main className="center-layout">
        <Notice>{error}</Notice>
      </main>
    );
  if (!organization)
    return <OrganizationPicker organizations={organizations} onSelect={selectOrganization} />;
  return (
    <Workspace
      user={user}
      organization={organization}
      organizations={organizations}
      onSwitch={() => {
        setOrganization(null);
      }}
      onSignedOut={() => {
        setUser(null);
        setOrganization(null);
        setOrganizations([]);
      }}
    />
  );
}
