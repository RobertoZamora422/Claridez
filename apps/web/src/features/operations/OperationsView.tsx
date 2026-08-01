import { useCallback, useMemo, useState, type SyntheticEvent } from "react";

import {
  ApiError,
  api,
  type OperationEvent,
  type OperationMembership,
  type PreparationItem,
} from "../../api";
import { Loading, Notice } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { message } from "../../shared/utilities";

const STATUS_LABELS: Record<OperationEvent["preparation"]["status"], string> = {
  preparing: "En preparación",
  ready: "Listo",
  in_progress: "En ejecución",
  completed: "Completado",
  cancelled: "Cancelado",
};

const ITEM_STATUS_LABELS: Record<PreparationItem["status"], string> = {
  pending: "Pendiente",
  in_progress: "En curso",
  blocked: "Bloqueado",
  completed: "Completado",
  not_applicable: "No aplica",
};

const SECTION_LABELS: Record<PreparationItem["section"], string> = {
  definitions: "Definiciones",
  setup: "Preparación",
  final_review: "Revisión final",
};

function localDate(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("es-EC", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(value));
}

function reorderTargets(items: PreparationItem[], item: PreparationItem) {
  const sectionItems = items.filter((entry) => entry.section === item.section);
  const sectionIndex = sectionItems.findIndex((entry) => entry.id === item.id);
  const up = sectionIndex > 0 ? sectionItems[sectionIndex - 1]?.id : undefined;
  if (sectionIndex < 0 || sectionIndex >= sectionItems.length - 1) return { up, down: undefined };
  const nextId = sectionItems[sectionIndex + 1]?.id;
  const nextIndex = items.findIndex((entry) => entry.id === nextId);
  return { up, down: items[nextIndex + 1]?.id ?? null };
}

function ItemEditor({
  item,
  itemBase,
  disabled,
  placeBeforeForUp,
  placeBeforeForDown,
  onUpdated,
  onReload,
}: {
  item: PreparationItem;
  itemBase: string;
  disabled: boolean;
  placeBeforeForUp: string | undefined;
  placeBeforeForDown: string | null | undefined;
  onUpdated: (item: PreparationItem, preparationRevision: number, status?: string) => void;
  onReload: () => Promise<void>;
}) {
  const [status, setStatus] = useState(item.status);
  const [statusNote, setStatusNote] = useState(item.status_note);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setSaving(true);
    setError("");
    try {
      const body = await api<{
        item: PreparationItem;
        preparation_revision: number;
        preparation?: { status: string };
      }>(`${itemBase}/items/${item.id}/`, {
        method: "PATCH",
        body: JSON.stringify({ revision: item.revision, status, status_note: statusNote }),
      });
      onUpdated(body.item, body.preparation_revision, body.preparation?.status);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setSaving(false);
    }
  }
  async function move(placeBeforeItemId: string | null) {
    setSaving(true);
    setError("");
    try {
      await api(`${itemBase}/items/${item.id}/`, {
        method: "PATCH",
        body: JSON.stringify({
          revision: item.revision,
          place_before_item_id: placeBeforeItemId,
        }),
      });
      await onReload();
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setSaving(false);
    }
  }
  return (
    <li className="operation-item" id={`operation-item-${item.id}`} tabIndex={-1}>
      <div className="operation-item__heading">
        <span className="operation-item__position">{item.position}</span>
        <div>
          <strong>{item.title}</strong>
          <small>
            {item.is_required ? "Obligatorio" : "Opcional"}
            {item.due_on ? ` · vence ${item.due_on}` : ""}
          </small>
        </div>
        <span className={`status status--${item.status}`}>{ITEM_STATUS_LABELS[item.status]}</span>
      </div>
      {item.resolved_at && item.resolved_by ? (
        <p className="resolution-note">
          Resuelto por {item.resolved_by.display_name} ·{" "}
          {new Date(item.resolved_at).toLocaleString("es-EC")}
        </p>
      ) : null}
      {!disabled ? (
        <div className="operation-item__controls">
          <div className="operation-item__order" aria-label={`Ordenar ${item.title}`}>
            <button
              type="button"
              className="button button--secondary"
              disabled={saving || placeBeforeForUp === undefined}
              onClick={() => {
                if (placeBeforeForUp !== undefined) void move(placeBeforeForUp);
              }}
            >
              Subir
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={saving || placeBeforeForDown === undefined}
              onClick={() => {
                if (placeBeforeForDown !== undefined) void move(placeBeforeForDown);
              }}
            >
              Bajar
            </button>
          </div>
          <label>
            Estado
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as PreparationItem["status"]);
              }}
            >
              {Object.entries(ITEM_STATUS_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {status === "blocked" || status === "not_applicable" ? (
            <label>
              Explicación
              <input
                value={statusNote}
                onChange={(event) => {
                  setStatusNote(event.target.value);
                }}
                required
              />
            </label>
          ) : null}
          <button
            className="button button--secondary"
            onClick={() => {
              void save();
            }}
            disabled={saving}
          >
            {saving ? "Guardando…" : "Guardar ítem"}
          </button>
        </div>
      ) : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

function PreparationNotes({
  event,
  base,
  onSaved,
}: {
  event: OperationEvent;
  base: string;
  onSaved: (updated: OperationEvent) => void;
}) {
  const [notes, setNotes] = useState(event.preparation.operational_notes);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setSaving(true);
    setError("");
    try {
      const updated = await api<OperationEvent>(`${base}/${event.reservation_id}/preparation/`, {
        method: "PATCH",
        body: JSON.stringify({ revision: event.preparation.revision, operational_notes: notes }),
      });
      onSaved(updated);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="operation-panel" aria-labelledby="operation-notes-title">
      <h2 id="operation-notes-title">Notas operativas</h2>
      <label>
        Indicaciones para el equipo
        <textarea
          rows={4}
          maxLength={4000}
          value={notes}
          onChange={(event_) => {
            setNotes(event_.target.value);
          }}
        />
      </label>
      <button
        className="button button--secondary"
        disabled={saving}
        onClick={() => {
          void save();
        }}
      >
        {saving ? "Guardando…" : "Guardar notas"}
      </button>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function NewItemForm({
  event,
  base,
  onCreated,
}: {
  event: OperationEvent;
  base: string;
  onCreated: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [section, setSection] = useState<PreparationItem["section"]>("definitions");
  const [required, setRequired] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event_: SyntheticEvent<HTMLFormElement>) {
    event_.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api(`${base}/${event.reservation_id}/items/`, {
        method: "POST",
        body: JSON.stringify({
          client_request_id: crypto.randomUUID(),
          title,
          section,
          is_required: required,
          notes: "",
        }),
      });
      setTitle("");
      setRequired(false);
      await onCreated();
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setSaving(false);
    }
  }
  return (
    <form
      className="operation-new-item"
      onSubmit={(event_) => {
        void submit(event_);
      }}
    >
      <h3>Añadir verificación</h3>
      <label>
        Título
        <input
          value={title}
          maxLength={160}
          required
          onChange={(event_) => {
            setTitle(event_.target.value);
          }}
        />
      </label>
      <label>
        Sección
        <select
          value={section}
          onChange={(event_) => {
            setSection(event_.target.value as PreparationItem["section"]);
          }}
        >
          {Object.entries(SECTION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={required}
          onChange={(event_) => {
            setRequired(event_.target.checked);
          }}
        />
        Obligatorio para declarar listo
      </label>
      <button className="button button--secondary" disabled={saving}>
        {saving ? "Añadiendo…" : "Añadir ítem"}
      </button>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

export function OperationsView({
  organizationId,
  canManage,
  canExecute,
}: {
  organizationId: string;
  canManage: boolean;
  canExecute: boolean;
}) {
  const base = `/api/v1/organizations/${organizationId}/operations/events`;
  const [events, setEvents] = useState<OperationEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OperationEvent | null>(null);
  const [assignees, setAssignees] = useState<OperationMembership[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [attentionFilter, setAttentionFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loadList = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ page_size: "100" });
    if (statusFilter) params.append("status", statusFilter);
    if (attentionFilter) params.set("attention", attentionFilter);
    try {
      const body = await api<{ results: OperationEvent[] }>(`${base}/?${params}`);
      setEvents(body.results);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [attentionFilter, base, statusFilter]);
  const loadDetail = useCallback(
    async (reservationId: string) => {
      setError("");
      try {
        const body = await api<OperationEvent>(`${base}/${reservationId}/`);
        setDetail(body);
      } catch (caught: unknown) {
        setError(message(caught));
      }
    },
    [base],
  );
  const loadAssignees = useCallback(async () => {
    if (!canManage) return;
    try {
      const body = await api<{ assignees: OperationMembership[] }>(
        `/api/v1/organizations/${organizationId}/operations/assignees/`,
      );
      setAssignees(body.assignees);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }, [canManage, organizationId]);
  useInitialLoad(loadList);
  useInitialLoad(loadAssignees);

  const groupedItems = useMemo(() => {
    const groups: Record<PreparationItem["section"], PreparationItem[]> = {
      definitions: [],
      setup: [],
      final_review: [],
    };
    for (const item of detail?.preparation.items ?? []) groups[item.section].push(item);
    return groups;
  }, [detail]);

  const readinessBlockers = useMemo(() => {
    if (!detail) return [];
    const items = detail.preparation.items ?? [];
    const blockers: { message: string; itemId?: string }[] = [];
    if (!detail.preparation.responsible)
      blockers.push({ message: "Asigna un responsable principal." });
    const baseline = items.filter((item) => item.baseline_key !== null);
    if (baseline.length !== 7)
      blockers.push({ message: "La baseline operativa no contiene sus siete verificaciones." });
    const pendingRequired = items.find(
      (item) => item.is_required && !["completed", "not_applicable"].includes(item.status),
    );
    if (pendingRequired)
      blockers.push({
        message: "Resuelve todas las verificaciones obligatorias.",
        itemId: pendingRequired.id,
      });
    const blocked = items.find((item) => item.status === "blocked");
    if (blocked) blockers.push({ message: "Resuelve los bloqueos.", itemId: blocked.id });
    const finalReview = items.find((item) => item.baseline_key === "final_readiness_review");
    if (finalReview?.status !== "completed")
      blockers.push({
        message: "Completa la revisión final.",
        ...(finalReview ? { itemId: finalReview.id } : {}),
      });
    return blockers;
  }, [detail]);

  async function assign(membershipId: string) {
    if (!detail) return;
    try {
      const body = await api<OperationEvent>(`${base}/${detail.reservation_id}/assign/`, {
        method: "POST",
        body: JSON.stringify({
          revision: detail.preparation.revision,
          responsible_membership_id: membershipId,
        }),
      });
      setDetail(body);
      setNotice("Responsable actualizado.");
    } catch (caught: unknown) {
      setError(message(caught));
      if (caught instanceof ApiError && caught.status === 409)
        await loadDetail(detail.reservation_id);
    }
  }

  async function command(commandName: "ready" | "start" | "complete") {
    if (!detail) return;
    const labels = {
      ready: "declarar listo",
      start: "iniciar la ejecución",
      complete: "completar el evento",
    };
    if (!window.confirm(`¿Confirmas ${labels[commandName]}?`)) return;
    try {
      const body = await api<OperationEvent>(`${base}/${detail.reservation_id}/${commandName}/`, {
        method: "POST",
        body: JSON.stringify({ revision: detail.preparation.revision }),
      });
      setDetail(body);
      setNotice(`Estado actualizado: ${STATUS_LABELS[body.preparation.status]}.`);
      await loadList();
    } catch (caught: unknown) {
      setError(message(caught));
      if (caught instanceof ApiError && caught.status === 409)
        await loadDetail(detail.reservation_id);
    }
  }

  if (selectedId && detail) {
    const frozen = ["in_progress", "completed", "cancelled"].includes(detail.preparation.status);
    return (
      <section aria-labelledby="operation-detail-title">
        <button
          className="back-button"
          onClick={() => {
            setSelectedId(null);
            setDetail(null);
          }}
        >
          ← Próximos eventos
        </button>
        <header className="operation-detail-header">
          <div>
            <p className="eyebrow">Preparación operativa</p>
            <h1 id="operation-detail-title">{detail.event.event_type}</h1>
            <p>
              {localDate(detail.event.starts_at, detail.event.timezone)} ·{" "}
              {detail.event.estimated_guests} invitados
            </p>
            <p>
              {detail.contact.display_name}
              {detail.contact.phone_e164 ? ` · ${detail.contact.phone_e164}` : ""}
            </p>
          </div>
          <span className={`status status--${detail.preparation.status}`}>
            {STATUS_LABELS[detail.preparation.status]}
          </span>
        </header>
        <div className="attention-strip" aria-label="Resumen de atención">
          <span>{detail.preparation.attention.pending_count} pendientes</span>
          <span>{detail.preparation.attention.overdue_count} vencidos</span>
          <span>{detail.preparation.attention.blocked_count} bloqueos</span>
        </div>
        {notice ? (
          <p className="success-message" aria-live="polite">
            {notice}
          </p>
        ) : null}
        {error ? <Notice>{error}</Notice> : null}
        <section className="operation-panel" aria-labelledby="responsible-title">
          <h2 id="responsible-title">Responsable principal</h2>
          <p>{detail.preparation.responsible?.display_name ?? "Sin asignar"}</p>
          {canManage && !["completed", "cancelled"].includes(detail.preparation.status) ? (
            <label>
              Cambiar responsable
              <select
                value={detail.preparation.responsible?.membership_id ?? ""}
                onChange={(event) => {
                  if (event.target.value) void assign(event.target.value);
                }}
              >
                <option value="">Selecciona una persona</option>
                {assignees.map((assignee) => (
                  <option key={assignee.membership_id} value={assignee.membership_id}>
                    {assignee.display_name} · {assignee.role}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </section>
        {canManage && !frozen ? (
          <PreparationNotes
            key={`${detail.reservation_id}-${String(detail.preparation.revision)}`}
            event={detail}
            base={base}
            onSaved={(updated) => {
              setDetail(updated);
              setNotice("Notas operativas actualizadas.");
            }}
          />
        ) : detail.preparation.operational_notes ? (
          <section className="operation-panel">
            <h2>Notas operativas</h2>
            <p>{detail.preparation.operational_notes}</p>
          </section>
        ) : null}
        <section className="operation-panel" aria-labelledby="checklist-title">
          <h2 id="checklist-title">Checklist</h2>
          {canManage && !frozen ? (
            <NewItemForm
              event={detail}
              base={base}
              onCreated={() => loadDetail(detail.reservation_id)}
            />
          ) : null}
          {(Object.keys(SECTION_LABELS) as PreparationItem["section"][]).map((section) => (
            <section
              key={section}
              className="operation-section"
              aria-labelledby={`section-${section}`}
            >
              <h3 id={`section-${section}`}>{SECTION_LABELS[section]}</h3>
              <ol>
                {groupedItems[section].map((item) => {
                  const targets = reorderTargets(detail.preparation.items ?? [], item);
                  return (
                    <ItemEditor
                      key={item.id}
                      item={item}
                      itemBase={`${base}/${detail.reservation_id}`}
                      disabled={!canManage || frozen}
                      placeBeforeForUp={targets.up}
                      placeBeforeForDown={targets.down}
                      onReload={() => loadDetail(detail.reservation_id)}
                      onUpdated={(updated, revision, preparationStatus) => {
                        setDetail((current) =>
                          current
                            ? {
                                ...current,
                                preparation: {
                                  ...current.preparation,
                                  status: (preparationStatus ??
                                    current.preparation
                                      .status) as OperationEvent["preparation"]["status"],
                                  revision,
                                  items: (current.preparation.items ?? []).map((entry) =>
                                    entry.id === updated.id ? updated : entry,
                                  ),
                                },
                              }
                            : current,
                        );
                        setNotice("Ítem actualizado.");
                      }}
                    />
                  );
                })}
              </ol>
            </section>
          ))}
        </section>
        <div className="operation-primary-action">
          {canManage && detail.preparation.status === "preparing" ? (
            <div>
              {readinessBlockers.length > 0 ? (
                <div className="readiness-blockers" role="status">
                  <strong>Antes de declarar listo:</strong>
                  <ul>
                    {readinessBlockers.map((blocker) => (
                      <li key={`${blocker.message}-${blocker.itemId ?? "preparation"}`}>
                        {blocker.itemId ? (
                          <button
                            type="button"
                            onClick={() => {
                              document
                                .getElementById(`operation-item-${String(blocker.itemId)}`)
                                ?.focus();
                            }}
                          >
                            {blocker.message}
                          </button>
                        ) : (
                          blocker.message
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <button
                className="button"
                disabled={readinessBlockers.length > 0}
                onClick={() => {
                  void command("ready");
                }}
              >
                Declarar evento listo
              </button>
            </div>
          ) : null}
          {canExecute && detail.preparation.status === "ready" ? (
            <button
              className="button"
              onClick={() => {
                void command("start");
              }}
            >
              Iniciar ejecución
            </button>
          ) : null}
          {canExecute && detail.preparation.status === "in_progress" ? (
            <button
              className="button"
              onClick={() => {
                void command("complete");
              }}
            >
              Completar evento
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="operations-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">Centro operativo</p>
          <h1 id="operations-title">Próximos eventos</h1>
          <p>Lo pendiente, bloqueado y listo para ejecutar.</p>
        </div>
      </header>
      <div className="operation-filters" aria-label="Filtros operativos">
        <label>
          Estado
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
            }}
          >
            <option value="">Activos</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Atención
          <select
            value={attentionFilter}
            onChange={(event) => {
              setAttentionFilter(event.target.value);
            }}
          >
            <option value="">Toda</option>
            <option value="overdue">Atrasada</option>
            <option value="upcoming">Próxima</option>
            <option value="blocked">Con bloqueos</option>
            <option value="ready">Lista</option>
            <option value="unassigned">Sin responsable</option>
          </select>
        </label>
      </div>
      {error ? <Notice>{error}</Notice> : null}
      {loading ? (
        <Loading label="Cargando eventos operativos…" />
      ) : events.length === 0 ? (
        <div className="empty-state">
          <h2>No hay eventos confirmados en este periodo</h2>
          <p>Prueba cambiando los filtros de la bandeja.</p>
        </div>
      ) : (
        <ul className="operation-event-list">
          {events.map((event) => (
            <li key={event.reservation_id}>
              <button
                onClick={() => {
                  setSelectedId(event.reservation_id);
                  void loadDetail(event.reservation_id);
                }}
              >
                <span>
                  <strong>{event.event.event_type}</strong>
                  <small>
                    {event.contact.display_name} ·{" "}
                    {localDate(event.event.starts_at, event.event.timezone)}
                  </small>
                </span>
                <span>
                  <span className={`status status--${event.preparation.status}`}>
                    {STATUS_LABELS[event.preparation.status]}
                  </span>
                  <small>
                    {event.preparation.attention.pending_count} pendientes ·{" "}
                    {event.preparation.attention.blocked_count} bloqueos
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
