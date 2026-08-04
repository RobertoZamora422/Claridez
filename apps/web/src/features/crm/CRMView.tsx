import { useCallback, useState, type SyntheticEvent } from "react";

import {
  api,
  type CrmIndicators,
  type CrmInteraction,
  type CrmOpportunity,
  type CrmPersonOverview,
  type CrmTask,
  type Person,
} from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formatDate, formText, localToInstant, message } from "../../shared/utilities";

type FormSubmitEvent = SyntheticEvent<HTMLFormElement, SubmitEvent>;
type MergeRole = "source" | "target";
type MergeCandidate = Pick<Person, "id" | "full_name" | "phone_e164" | "email" | "revision">;

const RESULT_LABELS = { open: "En curso", won: "Ganada", lost: "Perdida" } as const;
const HISTORY_KIND_LABELS: Record<string, string> = {
  cutover_state: "Estado existente al corte",
  created: "Solicitud creada",
  updated: "Solicitud actualizada",
  status_changed: "Cambio de estado",
};
const STATUS_LABELS: Record<string, string> = {
  new: "Nueva",
  quoted: "Cotizada",
  accepted: "Aceptada",
  confirmed: "Confirmada",
  closed_lost: "Perdida",
  cancelled: "Cancelada",
};
const TIMELINE_LABELS = {
  opportunity: "Oportunidad",
  interaction: "Interacción",
  task: "Tarea",
} as const;
const CONSENT_LABELS: Record<string, string> = {
  granted: "Concedido",
  revoked: "Revocado",
};

export function CRMView({
  organizationId,
  timeZone,
  capabilities,
}: {
  organizationId: string;
  timeZone: string;
  capabilities: Set<string>;
}) {
  const [opportunities, setOpportunities] = useState<CrmOpportunity[]>([]);
  const [indicators, setIndicators] = useState<CrmIndicators | null>(null);
  const [tasks, setTasks] = useState<CrmTask[]>([]);
  const [selectedOpportunity, setSelectedOpportunity] = useState<CrmOpportunity | null>(null);
  const [overview, setOverview] = useState<CrmPersonOverview | null>(null);
  const [matches, setMatches] = useState<Person[]>([]);
  const [mergeQuery, setMergeQuery] = useState("");
  const [mergeMatches, setMergeMatches] = useState<Person[]>([]);
  const [mergeCandidate, setMergeCandidate] = useState<MergeCandidate | null>(null);
  const [viewedPersonRole, setViewedPersonRole] = useState<MergeRole>("source");
  const [correctionOf, setCorrectionOf] = useState<CrmInteraction | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [opportunityBody, indicatorBody, taskBody] = await Promise.all([
        api<{ opportunities: CrmOpportunity[] }>(
          `/api/v1/organizations/${organizationId}/crm/opportunities/`,
        ),
        api<{ indicators: CrmIndicators }>(
          `/api/v1/organizations/${organizationId}/crm/indicators/`,
        ),
        api<{ tasks: CrmTask[] }>(`/api/v1/organizations/${organizationId}/crm/tasks/?status=open`),
      ]);
      setOpportunities(opportunityBody.opportunities);
      setIndicators(indicatorBody.indicators);
      setTasks(taskBody.tasks);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);
  useInitialLoad(load);

  const openOpportunity = async (id: string) => {
    setError("");
    try {
      setSelectedOpportunity(
        await api<CrmOpportunity>(
          `/api/v1/organizations/${organizationId}/crm/opportunities/${id}/`,
        ),
      );
      setOverview(null);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const openPerson = async (id: string) => {
    setError("");
    try {
      setOverview(
        await api<CrmPersonOverview>(`/api/v1/organizations/${organizationId}/crm/people/${id}/`),
      );
      setSelectedOpportunity(null);
      setMergeQuery("");
      setMergeMatches([]);
      setMergeCandidate(null);
      setViewedPersonRole("source");
    } catch (caught) {
      setError(message(caught));
    }
  };

  const searchMergePeople = async () => {
    if (!overview || !mergeQuery.trim()) return;
    setError("");
    try {
      const body = await api<{ people: Person[] }>(
        `/api/v1/organizations/${organizationId}/people/?q=${encodeURIComponent(mergeQuery.trim())}`,
      );
      setMergeMatches(body.people.filter((person) => person.id !== overview.person.id));
      setMergeCandidate(null);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const searchPeople = async (event: FormSubmitEvent) => {
    event.preventDefault();
    const query = formText(new FormData(event.currentTarget), "query");
    try {
      const body = await api<{ people: Person[] }>(
        `/api/v1/organizations/${organizationId}/people/?q=${encodeURIComponent(query)}`,
      );
      setMatches(body.people);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const recordInteraction = async (event: FormSubmitEvent) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const personId = overview?.person.id ?? selectedOpportunity?.person.id;
    if (!personId) return;
    try {
      await api(`/api/v1/organizations/${organizationId}/crm/interactions/`, {
        method: "POST",
        body: JSON.stringify({
          person_id: personId,
          event_request_id: selectedOpportunity?.id ?? null,
          channel: formText(data, "channel"),
          direction: formText(data, "direction"),
          occurred_at: new Date().toISOString(),
          summary: formText(data, "summary"),
          correction_of_id: correctionOf?.id ?? null,
        }),
      });
      setCorrectionOf(null);
      setNotice("Interacción registrada sin modificar la evidencia anterior.");
      if (overview) await openPerson(personId);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const createTask = async (event: FormSubmitEvent) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const personId = overview?.person.id ?? selectedOpportunity?.person.id;
    if (!personId) return;
    try {
      await api(`/api/v1/organizations/${organizationId}/crm/tasks/`, {
        method: "POST",
        body: JSON.stringify({
          person_id: personId,
          event_request_id: selectedOpportunity?.id ?? null,
          title: formText(data, "title"),
          due_at: localToInstant(formText(data, "due_at"), timeZone),
          next_contact_at: formText(data, "next_contact_at")
            ? localToInstant(formText(data, "next_contact_at"), timeZone)
            : null,
        }),
      });
      setNotice("Tarea registrada.");
      await load();
      if (overview) await openPerson(personId);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const completeTask = async (task: CrmTask) => {
    try {
      await api(`/api/v1/organizations/${organizationId}/crm/tasks/${task.id}/`, {
        method: "PATCH",
        body: JSON.stringify({ revision: task.revision, status: "completed" }),
      });
      setNotice("Tarea finalizada.");
      await load();
      if (overview) await openPerson(overview.person.id);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const recordConsent = async (event: FormSubmitEvent) => {
    event.preventDefault();
    if (!overview) return;
    const data = new FormData(event.currentTarget);
    const decision = formText(data, "decision");
    try {
      await api(`/api/v1/organizations/${organizationId}/people/${overview.person.id}/consents/`, {
        method: "POST",
        body: JSON.stringify({
          purpose: "seguimiento_comercial",
          channel: formText(data, "channel"),
          event_type: decision === "granted" ? "grant" : "revoke",
          decision,
          source: "registro_manual",
          occurred_at: new Date().toISOString(),
          evidence_reference: formText(data, "evidence"),
        }),
      });
      setNotice("Consentimiento registrado como nueva evidencia.");
      await openPerson(overview.person.id);
    } catch (caught) {
      setError(message(caught));
    }
  };

  const mergePerson = async (event: FormSubmitEvent) => {
    event.preventDefault();
    if (!overview || !mergeCandidate) return;
    const data = new FormData(event.currentTarget);
    const viewedPerson: MergeCandidate = overview.person;
    const source = viewedPersonRole === "source" ? viewedPerson : mergeCandidate;
    const target = viewedPersonRole === "target" ? viewedPerson : mergeCandidate;
    try {
      await api(`/api/v1/organizations/${organizationId}/people/merge/`, {
        method: "POST",
        body: JSON.stringify({
          source_person_id: source.id,
          target_person_id: target.id,
          source_revision: source.revision,
          target_revision: target.revision,
          reason: formText(data, "reason"),
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setNotice("Personas fusionadas; la historia permanece íntegra.");
      await load();
      await openPerson(target.id);
    } catch (caught) {
      setError(message(caught));
    }
  };

  if (loading) return <Loading label="Preparando la bandeja CRM…" />;

  const activePerson = overview?.person ?? selectedOpportunity?.person;
  const interactions = overview?.interactions ?? [];

  return (
    <section aria-labelledby="crm-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Relación comercial</p>
          <h1 id="crm-title">CRM y seguimiento</h1>
          <p className="muted">A quién contactar, por qué, cuándo y con qué historia.</p>
        </div>
        {(selectedOpportunity !== null || overview !== null) && (
          <button
            className="button button--secondary"
            onClick={() => {
              setSelectedOpportunity(null);
              setOverview(null);
            }}
          >
            Volver a la bandeja
          </button>
        )}
      </header>
      {error && <Notice>{error}</Notice>}
      {notice && <Notice tone="info">{notice}</Notice>}

      {!selectedOpportunity && !overview ? (
        <>
          {indicators && (
            <div className="crm-metrics" aria-label="Indicadores de seguimiento">
              {[
                ["Abiertas", indicators.open],
                ["Ganadas", indicators.won],
                ["Sin próxima acción", indicators.without_next_action],
                ["Tareas vencidas", indicators.overdue_tasks],
              ].map(([label, value]) => (
                <article key={label} className="crm-metric">
                  <span>{label}</span>
                  <strong>{value}</strong>
                </article>
              ))}
            </div>
          )}
          <form className="crm-search panel" onSubmit={(event) => void searchPeople(event)}>
            <label>
              Buscar o deduplicar persona
              <input name="query" placeholder="Nombre, teléfono, correo o alias" />
            </label>
            <button className="button button--secondary">Buscar</button>
          </form>
          {matches.length > 0 && (
            <div className="crm-search-results panel">
              <h2>Coincidencias</h2>
              {matches.map((person) => (
                <button key={person.id} onClick={() => void openPerson(person.id)}>
                  <strong>{person.full_name}</strong>
                  <small>{person.phone_e164}</small>
                </button>
              ))}
            </div>
          )}
          <div className="crm-layout">
            <div className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Pipeline real</p>
                  <h2>Oportunidades</h2>
                </div>
              </div>
              <div className="crm-opportunities">
                {opportunities.map((opportunity) => (
                  <button key={opportunity.id} onClick={() => void openOpportunity(opportunity.id)}>
                    <span>
                      <strong>{opportunity.person.full_name}</strong>
                      <small>{opportunity.event_type}</small>
                    </span>
                    <span>
                      <StatusBadge value={opportunity.status} />
                      <small>{RESULT_LABELS[opportunity.result]}</small>
                    </span>
                    <span>
                      <small>
                        {opportunity.next_action
                          ? formatDate(opportunity.next_action.action_at, timeZone)
                          : "Sin próxima acción"}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <aside className="panel crm-task-tray">
              <p className="eyebrow">Prioridades</p>
              <h2>Tareas y contactos</h2>
              {tasks.length === 0 ? (
                <p className="muted">No hay tareas pendientes.</p>
              ) : (
                tasks.map((task) => (
                  <article
                    key={task.id}
                    className={task.overdue ? "crm-task crm-task--overdue" : "crm-task"}
                  >
                    <strong>{task.title}</strong>
                    <small>{formatDate(task.action_at, timeZone)}</small>
                    <button
                      className="button button--ghost"
                      onClick={() => void completeTask(task)}
                    >
                      Marcar completada
                    </button>
                  </article>
                ))
              )}
            </aside>
          </div>
        </>
      ) : (
        <div className="crm-detail-grid">
          <div>
            {selectedOpportunity && (
              <article className="panel">
                <p className="eyebrow">Oportunidad integral</p>
                <h2>{selectedOpportunity.event_type}</h2>
                <button
                  className="crm-person-link"
                  onClick={() => void openPerson(selectedOpportunity.person.id)}
                >
                  {selectedOpportunity.person.full_name} · Ver persona integral
                </button>
                <dl className="details">
                  <div>
                    <dt>Estado</dt>
                    <dd>
                      <StatusBadge value={selectedOpportunity.status} />
                    </dd>
                  </div>
                  <div>
                    <dt>Resultado</dt>
                    <dd>{RESULT_LABELS[selectedOpportunity.result]}</dd>
                  </div>
                  <div>
                    <dt>Próxima acción</dt>
                    <dd>{selectedOpportunity.next_action?.title ?? "Sin definir"}</dd>
                  </div>
                  <div>
                    <dt>Necesidad</dt>
                    <dd>{selectedOpportunity.general_need}</dd>
                  </div>
                </dl>
                <h3>Historial comercial</h3>
                <ol className="crm-timeline">
                  {selectedOpportunity.history?.map((entry) => (
                    <li key={entry.id}>
                      <strong>{HISTORY_KIND_LABELS[entry.kind] ?? entry.kind}</strong>
                      <span>{STATUS_LABELS[entry.status] ?? entry.status}</span>
                      <small>{formatDate(entry.occurred_at ?? entry.recorded_at, timeZone)}</small>
                    </li>
                  ))}
                </ol>
              </article>
            )}
            {overview && (
              <article className="panel">
                <p className="eyebrow">Persona integral</p>
                <h2>{overview.person.full_name}</h2>
                <p>
                  {overview.person.phone_e164} · {overview.person.email ?? "Sin correo"}
                </p>
                <div className="crm-person-flags">
                  {overview.person.has_interest_history && <span>Historial como interesado</span>}
                  {overview.person.is_client && <span>Cliente por reserva confirmada</span>}
                </div>
                <h3>Timeline</h3>
                <ol className="crm-timeline">
                  {overview.timeline.map((entry, index) => (
                    <li key={`${entry.type}-${String(index)}`}>
                      <strong>{TIMELINE_LABELS[entry.type]}</strong>
                      <small>{formatDate(entry.at, timeZone)}</small>
                    </li>
                  ))}
                </ol>
                <h3>Consentimiento efectivo</h3>
                {overview.consent.effective.map((item) => (
                  <p key={`${item.purpose}-${item.channel}`}>
                    {item.purpose} · {item.channel}:{" "}
                    <strong>{CONSENT_LABELS[item.decision] ?? item.decision}</strong>
                  </p>
                ))}
              </article>
            )}
          </div>
          <aside>
            {activePerson && capabilities.has("interaction:record") && (
              <form
                className="panel form-stack"
                onSubmit={(event) => void recordInteraction(event)}
              >
                <h2>{correctionOf ? "Corregir interacción" : "Registrar interacción"}</h2>
                {correctionOf && (
                  <Notice tone="info">La evidencia original no será editada.</Notice>
                )}
                <label>
                  Canal
                  <select name="channel" defaultValue="phone_call">
                    <option value="phone_call">Llamada</option>
                    <option value="whatsapp">WhatsApp</option>
                    <option value="email">Correo</option>
                    <option value="in_person">Presencial</option>
                    <option value="other">Otro</option>
                  </select>
                </label>
                <label>
                  Dirección
                  <select name="direction" defaultValue="outbound">
                    <option value="outbound">Saliente</option>
                    <option value="inbound">Entrante</option>
                  </select>
                </label>
                <label>
                  Resumen minimizado
                  <textarea name="summary" maxLength={1000} required />
                </label>
                <button className="button button--primary">Guardar evidencia</button>
              </form>
            )}
            {overview && interactions.length > 0 && (
              <section className="panel">
                <h2>Interacciones</h2>
                {interactions.map((interaction) => (
                  <article key={interaction.id} className="crm-interaction">
                    <strong>{interaction.summary}</strong>
                    <small>{formatDate(interaction.occurred_at, timeZone)}</small>
                    <button
                      className="button button--ghost"
                      onClick={() => {
                        setCorrectionOf(interaction);
                      }}
                    >
                      Corregir con nueva entrada
                    </button>
                  </article>
                ))}
              </section>
            )}
            {activePerson && capabilities.has("task:manage") && (
              <form className="panel form-stack" onSubmit={(event) => void createTask(event)}>
                <h2>Nueva tarea</h2>
                <label>
                  Acción
                  <input name="title" required maxLength={180} />
                </label>
                <label>
                  Vencimiento
                  <input type="datetime-local" name="due_at" required />
                </label>
                <label>
                  Próximo contacto
                  <input type="datetime-local" name="next_contact_at" />
                </label>
                <button className="button button--primary">Crear tarea</button>
              </form>
            )}
            {overview && capabilities.has("consent:manage") && (
              <form className="panel form-stack" onSubmit={(event) => void recordConsent(event)}>
                <h2>Registrar consentimiento</h2>
                <label>
                  Canal
                  <select name="channel">
                    <option value="whatsapp">WhatsApp</option>
                    <option value="email">Correo</option>
                    <option value="phone">Teléfono</option>
                    <option value="other">Otro</option>
                  </select>
                </label>
                <label>
                  Decisión
                  <select name="decision">
                    <option value="granted">Concedido</option>
                    <option value="revoked">Revocado</option>
                  </select>
                </label>
                <label>
                  Evidencia mínima
                  <input name="evidence" required maxLength={240} />
                </label>
                <button className="button button--secondary">Añadir evento</button>
              </form>
            )}
            {overview && capabilities.has("person:merge") && (
              <form
                className="panel form-stack danger-zone crm-merge-flow"
                onSubmit={(event) => void mergePerson(event)}
              >
                <div>
                  <h2>Fusionar duplicado</h2>
                  <p>Busca y compara ambas personas. La historia original no se reescribe.</p>
                </div>
                <label>
                  Buscar coincidencias
                  <input
                    name="merge_query"
                    value={mergeQuery}
                    onChange={(event) => {
                      setMergeQuery(event.currentTarget.value);
                    }}
                    placeholder="Nombre, teléfono, correo o alias"
                  />
                </label>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void searchMergePeople()}
                >
                  Buscar coincidencias
                </button>
                {mergeMatches.length > 0 && (
                  <div className="crm-search-results crm-merge-matches" aria-label="Coincidencias">
                    <h3>Coincidencias encontradas</h3>
                    {mergeMatches.map((person) => (
                      <button
                        type="button"
                        key={person.id}
                        aria-pressed={mergeCandidate?.id === person.id}
                        onClick={() => {
                          setMergeCandidate(person);
                        }}
                      >
                        <strong>{person.full_name}</strong>
                        <small>{person.phone_e164}</small>
                        <small>{person.email ?? "Sin correo"}</small>
                      </button>
                    ))}
                  </div>
                )}
                {mergeCandidate && (
                  <>
                    <label>
                      Dirección de la fusión
                      <select
                        value={viewedPersonRole}
                        onChange={(event) => {
                          setViewedPersonRole(event.currentTarget.value as MergeRole);
                        }}
                      >
                        <option value="source">
                          Fusionar {overview.person.full_name} en la coincidencia
                        </option>
                        <option value="target">
                          Conservar {overview.person.full_name} como persona canónica
                        </option>
                      </select>
                    </label>
                    <dl className="crm-merge-summary">
                      <div>
                        <dt>Origen</dt>
                        <dd>
                          {viewedPersonRole === "source"
                            ? overview.person.full_name
                            : mergeCandidate.full_name}
                        </dd>
                      </div>
                      <div>
                        <dt>Destino canónico</dt>
                        <dd>
                          {viewedPersonRole === "target"
                            ? overview.person.full_name
                            : mergeCandidate.full_name}
                        </dd>
                      </div>
                    </dl>
                    <label>
                      Razón obligatoria
                      <textarea name="reason" required maxLength={500} />
                    </label>
                    <label className="check-row">
                      <input type="checkbox" name="confirmed" required />
                      Confirmo que revisé las coincidencias y la razón de la fusión.
                    </label>
                    <button className="button button--danger">Confirmar fusión</button>
                  </>
                )}
              </form>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}
