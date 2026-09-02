import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { p14ExternalApi } from "../../api";
import { BrandLogo } from "../../Brand";
import { Loading, Notice } from "../../shared/components";
import { message } from "../../shared/utilities";
import { AntiAbuse } from "../public/AntiAbuse";

interface PortalEventSummary {
  grant_id: string;
  scopes: string[];
  event: {
    id: string;
    status: string;
    event_type: string;
    starts_at: string;
    ends_at: string;
    timezone_name: string;
    venue_name: string;
    space_name: string;
    estimated_guests: number;
  };
}
interface Quotation {
  id: string;
  visible_number: string;
  version: number;
  status: string;
  withdrawn: boolean;
  is_expired: boolean;
  currency: string | null;
  total: string | null;
  valid_until: string | null;
  lines: { description: string; quantity: string; unit_label: string; total: string }[];
}
interface EventDetail {
  grant_id: string;
  event: PortalEventSummary["event"];
  quotations?: Quotation[];
  schedule?: null | {
    starts_at: string;
    ends_at: string;
    timezone_name: string;
    venue_name: string;
    space_name: string;
    status: string;
  };
  receivables?: null | {
    currency: string;
    original_total: string;
    balance: string;
    derived_status: string;
    next_due_on: string | null;
    next_due_amount: string | null;
    payments: {
      id: string;
      amount: string;
      currency: string;
      reported_at: string;
      method: string;
    }[];
    receipts: {
      id: string;
      visible_number: string;
      issued_at: string;
      document_available: boolean;
    }[];
  };
}
interface PortalDocument {
  issued_version_id: string;
  artifact_id: string;
  title: string;
  instrument_type: string;
  version: number;
  issued_at: string | null;
  artifact_sha256: string;
  size_bytes: number;
  media_type: string;
  is_current: boolean;
  accepted_at: string | null;
  acceptance_manifestation_text: string;
  acceptance_manifestation_version: string;
}

function dateTime(value: string | null | undefined): string {
  return value
    ? new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      )
    : "—";
}

function money(value: string | null | undefined, currency = "USD"): string {
  return value === null || value === undefined
    ? "—"
    : new Intl.NumberFormat("es-EC", { style: "currency", currency }).format(Number(value));
}

export function ClientPortalView() {
  const query = new URLSearchParams(window.location.search);
  const [formLocator, setFormLocator] = useState(query.get("form") ?? "");
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [challengeKind, setChallengeKind] = useState<"authentication" | "recovery">(
    "authentication",
  );
  const [contact, setContact] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [antiabuseToken, setAntiabuseToken] = useState("");
  const [antiabuseReset, setAntiabuseReset] = useState(0);
  const [events, setEvents] = useState<PortalEventSummary[]>([]);
  const [selectedGrant, setSelectedGrant] = useState("");
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [documents, setDocuments] = useState<PortalDocument[]>([]);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadSession = useCallback(async () => {
    try {
      const body = await p14ExternalApi<{ authenticated: boolean; events: PortalEventSummary[] }>(
        "/api/v1/portal/session/",
      );
      setAuthenticated(body.authenticated);
      setEvents(body.events);
      if (body.events[0]) {
        setSelectedGrant((current) => (current ? current : (body.events[0]?.grant_id ?? "")));
      }
    } catch {
      setAuthenticated(false);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSession();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [loadSession]);

  useEffect(() => {
    if (!authenticated || !selectedGrant) return;
    void Promise.all([
      p14ExternalApi<EventDetail>(`/api/v1/portal/events/${selectedGrant}/`),
      p14ExternalApi<{ documents: PortalDocument[] }>(
        `/api/v1/portal/events/${selectedGrant}/documents/`,
      ),
    ])
      .then(([eventBody, documentBody]) => {
        setDetail(eventBody);
        setDocuments(documentBody.documents);
      })
      .catch((caught: unknown) => {
        setError(message(caught));
      });
  }, [authenticated, selectedGrant]);

  async function requestChallenge(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await p14ExternalApi<{ challenge: string; message: string }>(
        "/api/v1/portal/auth/challenges/",
        {
          method: "POST",
          body: JSON.stringify({
            form_locator: formLocator,
            channel,
            contact,
            kind: challengeKind,
            antiabuse_token: antiabuseToken,
            antiabuse_hostname: window.location.hostname,
          }),
        },
      );
      setChallenge(body.challenge);
      setNotice(body.message);
    } catch (caught: unknown) {
      setError(message(caught));
      setAntiabuseReset((current) => current + 1);
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const value = challenge.includes(".") ? challenge : `${challenge}.${code}`;
      await p14ExternalApi("/api/v1/portal/auth/verify/", {
        method: "POST",
        body: JSON.stringify({ challenge: value }),
      });
      setAuthenticated(true);
      setChallenge("");
      await loadSession();
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function acceptDocument(document: PortalDocument) {
    if (!window.confirm(document.acceptance_manifestation_text)) return;
    setBusy(true);
    setError("");
    try {
      await p14ExternalApi(`/api/v1/portal/events/${selectedGrant}/documents/accept/`, {
        method: "POST",
        body: JSON.stringify({
          issued_version_id: document.issued_version_id,
          artifact_id: document.artifact_id,
          artifact_sha256: document.artifact_sha256,
          manifestation_text: document.acceptance_manifestation_text,
          manifestation_version: document.acceptance_manifestation_version,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setNotice("La aceptación documental fue registrada por Documents.");
      const body = await p14ExternalApi<{ documents: PortalDocument[] }>(
        `/api/v1/portal/events/${selectedGrant}/documents/`,
      );
      setDocuments(body.documents);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function preference(purpose: string, allow: boolean) {
    setError("");
    try {
      await p14ExternalApi("/api/v1/portal/preferences/", {
        method: "POST",
        body: JSON.stringify({ grant_id: selectedGrant, channel: "email", purpose, allow }),
      });
      setNotice(
        allow
          ? "La preferencia se registró como una acción explícita del cliente."
          : "La baja se registró en Communications sin modificar ConsentEvent.",
      );
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  if (loading)
    return (
      <main className="external-surface">
        <Loading label="Comprobando tu sesión…" />
      </main>
    );

  if (!authenticated)
    return (
      <main className="external-surface portal-login">
        <BrandLogo />
        <section className="external-card" aria-labelledby="portal-access-title">
          <div>
            <p className="eyebrow">Portal seguro</p>
            <h1 id="portal-access-title">Accede a tus eventos</h1>
            <p>Tu acceso es externo y limitado. No crea una membresía del workspace.</p>
          </div>
          {!challenge ? (
            <form className="structured-form" onSubmit={(event) => void requestChallenge(event)}>
              <label>
                Motivo
                <select
                  value={challengeKind}
                  onChange={(event) => {
                    setChallengeKind(event.target.value as "authentication" | "recovery");
                  }}
                >
                  <option value="authentication">Acceder al portal</option>
                  <option value="recovery">Recuperar acceso</option>
                </select>
              </label>
              <label>
                Código del formulario
                <input
                  required
                  value={formLocator}
                  onChange={(event) => {
                    setFormLocator(event.target.value);
                  }}
                />
              </label>
              <label>
                Canal
                <select
                  value={channel}
                  onChange={(event) => {
                    setChannel(event.target.value as typeof channel);
                  }}
                >
                  <option value="email">Correo</option>
                  <option value="whatsapp">WhatsApp</option>
                </select>
              </label>
              <label>
                {channel === "email" ? "Correo" : "Teléfono"}
                <input
                  required
                  autoComplete={channel === "email" ? "email" : "tel"}
                  value={contact}
                  onChange={(event) => {
                    setContact(event.target.value);
                  }}
                />
              </label>
              <AntiAbuse
                action="portal_challenge"
                resetKey={antiabuseReset}
                onToken={setAntiabuseToken}
              />
              <button className="button" disabled={busy || !antiabuseToken}>
                Solicitar acceso
              </button>
            </form>
          ) : (
            <form className="structured-form" onSubmit={(event) => void verify(event)}>
              <p role="status">{notice}</p>
              <label>
                Código recibido
                <input
                  required
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(event) => {
                    setCode(event.target.value);
                  }}
                />
              </label>
              <button className="button" disabled={busy}>
                Verificar y entrar
              </button>
              <button
                className="button button--ghost"
                type="button"
                onClick={() => {
                  setChallenge("");
                }}
              >
                Solicitar otro código
              </button>
            </form>
          )}
          {error ? <Notice>{error}</Notice> : null}
        </section>
      </main>
    );

  return (
    <div className="client-portal-shell">
      <header className="client-portal-header">
        <BrandLogo theme="light" />
        <div className="button-row">
          <button
            className="button button--ghost"
            onClick={() =>
              void p14ExternalApi("/api/v1/portal/session/", { method: "POST" }).then(() => {
                setNotice("La sesión segura fue rotada.");
              })
            }
          >
            Renovar sesión
          </button>
          <button
            className="button button--ghost"
            onClick={() =>
              void p14ExternalApi("/api/v1/portal/session/", { method: "DELETE" }).finally(() => {
                setAuthenticated(false);
                setEvents([]);
              })
            }
          >
            Cerrar sesión
          </button>
        </div>
      </header>
      <main className="client-portal-main">
        <aside className="portal-event-list" aria-label="Tus solicitudes y eventos">
          <h2>Tus eventos</h2>
          {events.map((item) => (
            <button
              key={item.grant_id}
              aria-current={selectedGrant === item.grant_id ? "page" : undefined}
              onClick={() => {
                setSelectedGrant(item.grant_id);
              }}
            >
              <strong>{item.event.event_type}</strong>
              <span>{dateTime(item.event.starts_at)}</span>
              <small>{item.event.status}</small>
            </button>
          ))}
        </aside>
        <section className="portal-content" aria-live="polite">
          {notice ? (
            <div className="success-panel" role="status">
              {notice}
            </div>
          ) : null}
          {error ? <Notice>{error}</Notice> : null}
          {!detail ? (
            <Loading label="Cargando el evento…" />
          ) : (
            <>
              <section className="portal-card">
                <p className="eyebrow">Estado general</p>
                <h1>{detail.event.event_type}</h1>
                <dl className="summary-grid">
                  <div>
                    <dt>Estado</dt>
                    <dd>{detail.event.status}</dd>
                  </div>
                  <div>
                    <dt>Fecha deseada</dt>
                    <dd>{dateTime(detail.event.starts_at)}</dd>
                  </div>
                  <div>
                    <dt>Lugar</dt>
                    <dd>
                      {detail.event.venue_name} · {detail.event.space_name}
                    </dd>
                  </div>
                  <div>
                    <dt>Invitados</dt>
                    <dd>{detail.event.estimated_guests}</dd>
                  </div>
                </dl>
              </section>
              <section className="portal-card">
                <h2>Propuesta</h2>
                {!detail.quotations?.length ? (
                  <p>Aún no hay una propuesta emitida.</p>
                ) : (
                  detail.quotations.map((quotation) => (
                    <article key={quotation.id} className="portal-item">
                      <div>
                        <strong>
                          {quotation.withdrawn ? "Propuesta retirada" : quotation.visible_number}
                        </strong>
                        <span>
                          Versión {quotation.version} · {quotation.status}
                          {quotation.is_expired ? " · vencida" : ""}
                        </span>
                      </div>
                      {!quotation.withdrawn ? (
                        <>
                          <p>Total: {money(quotation.total, quotation.currency ?? "")}</p>
                          <p>Válida hasta: {dateTime(quotation.valid_until)}</p>
                          <ul>
                            {quotation.lines.map((line, index) => (
                              <li key={`${quotation.id}-${String(index)}`}>
                                {line.description} · {line.quantity} {line.unit_label} ·{" "}
                                {money(line.total, quotation.currency ?? "")}
                              </li>
                            ))}
                          </ul>
                        </>
                      ) : (
                        <p>Esta versión ya no está disponible para uso.</p>
                      )}
                    </article>
                  ))
                )}
                <small>
                  La propuesta es de solo lectura; P14 no incorpora aceptación comercial externa.
                </small>
              </section>
              <section className="portal-card">
                <h2>Agenda confirmada</h2>
                {detail.schedule ? (
                  <dl className="summary-grid">
                    <div>
                      <dt>Fecha</dt>
                      <dd>{dateTime(detail.schedule.starts_at)}</dd>
                    </div>
                    <div>
                      <dt>Lugar</dt>
                      <dd>
                        {detail.schedule.venue_name} · {detail.schedule.space_name}
                      </dd>
                    </div>
                    <div>
                      <dt>Zona</dt>
                      <dd>{detail.schedule.timezone_name}</dd>
                    </div>
                    <div>
                      <dt>Estado</dt>
                      <dd>{detail.schedule.status}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>La agenda se mostrará cuando Scheduling tenga una reserva vinculada.</p>
                )}
              </section>
              <section className="portal-card">
                <h2>Documentos y contratos</h2>
                {!documents.length ? (
                  <p>No hay documentos emitidos disponibles.</p>
                ) : (
                  documents.map((document) => (
                    <article className="portal-item" key={document.issued_version_id}>
                      <div>
                        <strong>{document.title}</strong>
                        <span>
                          Versión {document.version}
                          {document.is_current ? " · vigente" : " · sustituida"}
                        </span>
                      </div>
                      <div className="button-row">
                        <a
                          className="button button--ghost"
                          href={`/api/v1/portal/events/${selectedGrant}/documents/${document.issued_version_id}/${document.artifact_id}/download/?sha256=${document.artifact_sha256}`}
                        >
                          Descargar
                        </a>
                        {document.is_current && !document.accepted_at ? (
                          <button
                            className="button"
                            disabled={busy}
                            onClick={() => void acceptDocument(document)}
                          >
                            Aceptar documento
                          </button>
                        ) : null}
                      </div>
                      <small>
                        {document.accepted_at
                          ? `Aceptado: ${dateTime(document.accepted_at)}`
                          : document.is_current
                            ? "Pendiente de aceptación"
                            : "Conservado como versión sustituida"}
                      </small>
                    </article>
                  ))
                )}
              </section>
              <section className="portal-card">
                <h2>Saldo y pagos</h2>
                {!detail.receivables ? (
                  <p>No existe una obligación de cobro para esta solicitud.</p>
                ) : (
                  <>
                    <dl className="summary-grid">
                      <div>
                        <dt>Saldo</dt>
                        <dd>{money(detail.receivables.balance, detail.receivables.currency)}</dd>
                      </div>
                      <div>
                        <dt>Total</dt>
                        <dd>
                          {money(detail.receivables.original_total, detail.receivables.currency)}
                        </dd>
                      </div>
                      <div>
                        <dt>Próximo vencimiento</dt>
                        <dd>{detail.receivables.next_due_on ?? "—"}</dd>
                      </div>
                      <div>
                        <dt>Próximo importe</dt>
                        <dd>
                          {money(detail.receivables.next_due_amount, detail.receivables.currency)}
                        </dd>
                      </div>
                    </dl>
                    <h3>Pagos registrados</h3>
                    {detail.receivables.payments.length ? (
                      <ul>
                        {detail.receivables.payments.map((payment) => (
                          <li key={payment.id}>
                            {dateTime(payment.reported_at)} ·{" "}
                            {money(payment.amount, payment.currency)} · {payment.method}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No hay pagos registrados.</p>
                    )}
                    <h3>Recibos</h3>
                    {detail.receivables.receipts.length ? (
                      <ul>
                        {detail.receivables.receipts.map((receipt) => (
                          <li key={receipt.id}>
                            {receipt.visible_number} · {dateTime(receipt.issued_at)}
                            {receipt.document_available ? " · documento disponible" : ""}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No hay recibos emitidos.</p>
                    )}
                  </>
                )}
                <small>
                  El portal no inicia pagos electrónicos ni registra hechos del proveedor.
                </small>
              </section>
              <section className="portal-card">
                <h2>Preferencias</h2>
                <p>
                  Las bajas se conservan en Communications y no modifican automáticamente el
                  consentimiento de People.
                </p>
                <div className="button-row">
                  <button
                    className="button button--ghost"
                    onClick={() => void preference("service_update", false)}
                  >
                    Dar de baja actualizaciones
                  </button>
                  <button
                    className="button button--ghost"
                    onClick={() => void preference("service_update", true)}
                  >
                    Volver a permitir actualizaciones
                  </button>
                </div>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
