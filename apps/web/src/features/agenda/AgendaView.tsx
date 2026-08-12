import { useCallback, useMemo, useState } from "react";

import { api, type CalendarEntry, type CalendarPayload, type Venue } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formatDate, message, toInputDate } from "../../shared/utilities";

type CalendarView = "day" | "week" | "month";
interface ScheduleEvent {
  id: string;
  kind: string;
  reason: string | null;
  occurred_at: string;
  previous_snapshot: Record<string, unknown>;
  new_snapshot: Record<string, unknown>;
}

function newKey() {
  return globalThis.crypto.randomUUID();
}

function defaultLocal(date: string, hour: string) {
  return `${date}T${hour}`;
}

function instantToLocal(value: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

function localDateKey(value: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function localDateLabel(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  const formatted = new Intl.DateTimeFormat("es-EC", {
    timeZone: "UTC",
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1, 12)));
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

const typeLabels = {
  hold: "Reserva temporal",
  reservation: "Reserva confirmada",
  block: "Bloqueo interno",
};

const scheduleEventLabels: Record<string, string> = {
  cutover_snapshot: "Snapshot de cutover",
  reservation_hold_created: "Reserva temporal creada",
  reservation_confirmed: "Reserva confirmada",
  reservation_expired: "Reserva temporal vencida",
  reservation_rescheduled: "Reserva reprogramada",
  reservation_cancelled: "Reserva cancelada",
  block_created: "Bloqueo creado",
  block_released: "Bloqueo liberado",
  block_cancelled: "Bloqueo anulado",
};

export function AgendaView({
  organizationId,
  timeZone,
  capabilities,
}: {
  organizationId: string;
  timeZone: string;
  capabilities: Set<string>;
}) {
  const [view, setView] = useState<CalendarView>("week");
  const [anchorDate, setAnchorDate] = useState(toInputDate(new Date()));
  const [venues, setVenues] = useState<Venue[]>([]);
  const [venueId, setVenueId] = useState("");
  const [spaceId, setSpaceId] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [calendar, setCalendar] = useState<CalendarPayload | null>(null);
  const [selected, setSelected] = useState<CalendarEntry | null>(null);
  const [history, setHistory] = useState<ScheduleEvent[]>([]);
  const [mode, setMode] = useState<"" | "block" | "reschedule" | "cancel" | "confirm">("");
  const [reason, setReason] = useState("");
  const [startsAtLocal, setStartsAtLocal] = useState(defaultLocal(anchorDate, "09:00"));
  const [endsAtLocal, setEndsAtLocal] = useState(defaultLocal(anchorDate, "11:00"));
  const [targetSpaceId, setTargetSpaceId] = useState("");
  const [blockScope, setBlockScope] = useState<"spaces" | "venue">("spaces");
  const [depositAmount, setDepositAmount] = useState("");
  const [depositReference, setDepositReference] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ view, anchor_date: anchorDate });
      if (venueId) params.set("venue_id", venueId);
      if (spaceId) params.set("space_id", spaceId);
      if (typeFilter) params.append("types", typeFilter);
      const [venueBody, calendarBody] = await Promise.all([
        api<{ venues: Venue[] }>(`/api/v1/organizations/${organizationId}/venues/`),
        api<CalendarPayload>(
          `/api/v1/organizations/${organizationId}/scheduling/calendar/?${params}`,
        ),
      ]);
      setVenues(venueBody.venues);
      setCalendar(calendarBody);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [anchorDate, organizationId, spaceId, typeFilter, venueId, view]);

  useInitialLoad(load);

  const spaces = useMemo(
    () =>
      venues
        .filter((venue) => !venueId || venue.id === venueId)
        .flatMap((venue) =>
          venue.spaces
            .filter((space) => space.is_active)
            .map((space) => ({ ...space, venueName: venue.name })),
        ),
    [venueId, venues],
  );

  const lanes = useMemo(() => {
    const entries = calendar?.entries ?? [];
    const grouped = new Map<string, CalendarEntry[]>();
    for (const entry of entries) {
      const current = grouped.get(entry.space_id) ?? [];
      current.push(entry);
      grouped.set(entry.space_id, current);
    }
    return spaces
      .filter((space) => !spaceId || space.id === spaceId)
      .map((space) => ({ space, entries: grouped.get(space.id) ?? [] }));
  }, [calendar?.entries, spaceId, spaces]);

  const mobileDays = useMemo(() => {
    const grouped = new Map<string, CalendarEntry[]>();
    for (const entry of calendar?.entries ?? []) {
      const key = localDateKey(entry.starts_at, timeZone);
      const current = grouped.get(key) ?? [];
      current.push(entry);
      grouped.set(key, current);
    }
    return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [calendar?.entries, timeZone]);

  const selectEntry = async (entry: CalendarEntry) => {
    setSelected(entry);
    setMode("");
    setReason("");
    setTargetSpaceId(entry.space_id);
    setStartsAtLocal(instantToLocal(entry.starts_at, entry.event_timezone));
    setEndsAtLocal(instantToLocal(entry.ends_at, entry.event_timezone));
    setHistory([]);
    if (entry.type !== "block") {
      try {
        const body = await api<{ results: ScheduleEvent[] }>(
          `/api/v1/organizations/${organizationId}/reservations/${entry.id}/schedule-history/`,
        );
        setHistory(body.results);
      } catch (caught) {
        setError(message(caught));
      }
    }
  };

  const run = async (operation: () => Promise<unknown>, success: string) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await operation();
      setNotice(success);
      setMode("");
      setSelected(null);
      setHistory([]);
      await load();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setSaving(false);
    }
  };

  const createBlock = () =>
    run(
      () =>
        api(`/api/v1/organizations/${organizationId}/scheduling/blocks/`, {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: newKey(),
            scope: blockScope,
            venue_id: venueId || spaces.find((space) => space.id === targetSpaceId)?.venue_id,
            space_ids: blockScope === "spaces" ? [targetSpaceId] : [],
            starts_at_local: startsAtLocal,
            ends_at_local: endsAtLocal,
            timezone: timeZone,
            reason,
          }),
        }),
      "Bloqueo creado y disponibilidad actualizada.",
    );

  const reschedule = () => {
    if (!selected) return Promise.resolve();
    return run(
      () =>
        api(`/api/v1/organizations/${organizationId}/reservations/${selected.id}/reschedule/`, {
          method: "POST",
          body: JSON.stringify({
            revision: selected.revision,
            idempotency_key: newKey(),
            space_id: targetSpaceId,
            starts_at_local: startsAtLocal,
            ends_at_local: endsAtLocal,
            timezone: timeZone,
            reason,
            commercial_terms_unchanged: true,
            carry_free_item_ids: [],
          }),
        }),
      "Reserva reprogramada. La fecha anterior permanece en la historia.",
    );
  };

  const cancelReservation = () => {
    if (!selected) return Promise.resolve();
    return run(
      () =>
        api(`/api/v1/organizations/${organizationId}/reservations/${selected.id}/cancel/`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        }),
      "Reserva cancelada y espacio liberado.",
    );
  };

  const confirmHold = () => {
    if (!selected) return Promise.resolve();
    const waiver = capabilities.has("reservation:waive_deposit") && !depositAmount;
    return run(
      () =>
        api(`/api/v1/organizations/${organizationId}/reservations/${selected.id}/confirm/`, {
          method: "POST",
          body: JSON.stringify(
            waiver
              ? { kind: "waiver", waiver_reason: reason }
              : {
                  kind: "external_deposit",
                  recognized_amount: depositAmount,
                  reported_at: new Date().toISOString(),
                  reference: depositReference,
                },
          ),
        }),
      "Reserva confirmada y preparación operativa creada.",
    );
  };

  const terminateBlock = (action: "release" | "cancel") => {
    if (!selected) return Promise.resolve();
    return run(
      () =>
        api(`/api/v1/organizations/${organizationId}/scheduling/blocks/${selected.id}/${action}/`, {
          method: "POST",
          body: JSON.stringify({ revision: selected.revision, reason }),
        }),
      action === "release" ? "Bloqueo liberado." : "Bloqueo cancelado.",
    );
  };

  const exportParams = new URLSearchParams({ view, anchor_date: anchorDate });
  if (venueId) exportParams.set("venue_id", venueId);
  if (spaceId) exportParams.set("space_id", spaceId);

  return (
    <section aria-labelledby="agenda-title" className="schedule-page">
      <header className="page-header schedule-header">
        <div>
          <p className="eyebrow">Centro de control temporal</p>
          <h1 id="agenda-title">Agenda y disponibilidad</h1>
          <p className="muted">Horarios bloqueados en {timeZone}.</p>
          <p className="muted">Disponibilidad real; los intervalos adyacentes son válidos.</p>
        </div>
        <div className="schedule-header-actions">
          {capabilities.has("schedule:block") && (
            <button
              className="button button--secondary"
              onClick={() => {
                setSelected(null);
                setMode("block");
                setReason("");
                setTargetSpaceId(spaceId !== "" ? spaceId : (spaces[0]?.id ?? ""));
                setStartsAtLocal(defaultLocal(anchorDate, "09:00"));
                setEndsAtLocal(defaultLocal(anchorDate, "11:00"));
              }}
            >
              Crear bloqueo
            </button>
          )}
          {capabilities.has("schedule:export") && (
            <a
              className="button button--ghost"
              href={`/api/v1/organizations/${organizationId}/scheduling/calendar.ics?${exportParams}`}
              download
            >
              Exportar .ics
            </a>
          )}
        </div>
      </header>

      <div className="schedule-toolbar" aria-label="Controles de agenda">
        <div className="segmented" aria-label="Vista de calendario">
          {(["day", "week", "month"] as const).map((option) => (
            <button
              key={option}
              aria-pressed={view === option}
              onClick={() => {
                setView(option);
              }}
            >
              {option === "day" ? "Día" : option === "week" ? "Semana" : "Mes"}
            </button>
          ))}
        </div>
        <label>
          Fecha
          <input
            type="date"
            value={anchorDate}
            onChange={(event) => {
              setAnchorDate(event.target.value);
            }}
          />
        </label>
        <label>
          Sede
          <select
            value={venueId}
            onChange={(event) => {
              setVenueId(event.target.value);
              setSpaceId("");
            }}
          >
            <option value="">Todas</option>
            {venues
              .filter((venue) => venue.is_active)
              .map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Espacio
          <select
            value={spaceId}
            onChange={(event) => {
              setSpaceId(event.target.value);
            }}
          >
            <option value="">Todos</option>
            {spaces.map((space) => (
              <option key={space.id} value={space.id}>
                {space.venueName} · {space.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tipo
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value);
            }}
          >
            <option value="">Todos</option>
            <option value="reservation">Confirmadas</option>
            <option value="hold">Temporales</option>
            <option value="block">Bloqueos</option>
          </select>
        </label>
        <button className="button button--ghost" onClick={() => void load()}>
          Actualizar
        </button>
      </div>

      <div className="schedule-live" aria-live="polite" aria-atomic="true">
        {error && <Notice>{error}</Notice>}
        {notice && <Notice>{notice}</Notice>}
      </div>

      {loading ? (
        <Loading />
      ) : (
        <div className="schedule-layout">
          <div className="schedule-mobile-list" aria-label="Agenda agrupada por día">
            {mobileDays.length === 0 ? (
              <div className="empty-state">
                <h2>Período disponible</h2>
                <p>No hay reservas ni bloqueos en el período seleccionado.</p>
              </div>
            ) : (
              mobileDays.map(([dateKey, entries]) => (
                <section
                  className="schedule-mobile-day"
                  key={dateKey}
                  aria-labelledby={`schedule-mobile-day-${dateKey}`}
                >
                  <h2 id={`schedule-mobile-day-${dateKey}`}>{localDateLabel(dateKey)}</h2>
                  <div className="schedule-mobile-day-entries">
                    {entries.map((entry) => (
                      <button
                        key={`${entry.type}-${entry.id}-${entry.space_id}`}
                        className={`schedule-entry schedule-entry--${entry.type}`}
                        onClick={() => void selectEntry(entry)}
                      >
                        <span className="schedule-entry-icon" aria-hidden="true">
                          {entry.type === "block" ? "■" : entry.type === "hold" ? "◷" : "●"}
                        </span>
                        <span>
                          <strong>{typeLabels[entry.type]}</strong>
                          <small>
                            {entry.venue_name} · {entry.space_name}
                          </small>
                          <small>
                            {formatDate(entry.starts_at, timeZone)} —{" "}
                            {formatDate(entry.ends_at, timeZone)}
                          </small>
                        </span>
                        <StatusBadge value={entry.status} />
                      </button>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
          <div className={`schedule-calendar schedule-calendar--${view}`}>
            {(calendar?.entries.length ?? 0) === 0 && lanes.length > 0 && (
              <div className="empty-state">
                <h2>Semana disponible</h2>
                <p>No hay reservas ni bloqueos en el período seleccionado.</p>
              </div>
            )}
            {lanes.length === 0 ? (
              <div className="empty-state">
                <h2>No hay espacios activos</h2>
              </div>
            ) : (
              lanes.map(({ space, entries }) => (
                <section
                  className="schedule-lane"
                  key={space.id}
                  aria-labelledby={`lane-${space.id}`}
                >
                  <header>
                    <h2 id={`lane-${space.id}`}>{space.name}</h2>
                    <small>{space.venueName}</small>
                  </header>
                  <div className="schedule-lane-events">
                    {entries.length === 0 ? (
                      <p className="schedule-available">Disponible en este período</p>
                    ) : (
                      entries.map((entry) => (
                        <button
                          key={`${entry.type}-${entry.id}-${entry.space_id}`}
                          className={`schedule-entry schedule-entry--${entry.type}`}
                          onClick={() => void selectEntry(entry)}
                        >
                          <span className="schedule-entry-icon" aria-hidden="true">
                            {entry.type === "block" ? "■" : entry.type === "hold" ? "◷" : "●"}
                          </span>
                          <span>
                            <strong>{typeLabels[entry.type]}</strong>
                            <small>
                              {formatDate(entry.starts_at, timeZone)} —{" "}
                              {formatDate(entry.ends_at, timeZone)}
                            </small>
                          </span>
                          <StatusBadge value={entry.status} />
                        </button>
                      ))
                    )}
                  </div>
                </section>
              ))
            )}
          </div>

          {(selected !== null || mode === "block") && (
            <aside className="schedule-detail" aria-labelledby="schedule-detail-title">
              <div className="schedule-detail-heading">
                <div>
                  <p className="eyebrow">{mode === "block" && !selected ? "Nuevo" : "Detalle"}</p>
                  <h2 id="schedule-detail-title">
                    {selected ? typeLabels[selected.type] : "Bloqueo de agenda"}
                  </h2>
                </div>
                <button
                  className="icon-button"
                  aria-label="Cerrar detalle"
                  onClick={() => {
                    setSelected(null);
                    setMode("");
                  }}
                >
                  ×
                </button>
              </div>

              {selected && (
                <>
                  <StatusBadge value={selected.status} />
                  <dl className="schedule-facts">
                    <div>
                      <dt>Sede y espacio</dt>
                      <dd>
                        {selected.venue_name} · {selected.space_name}
                      </dd>
                    </div>
                    <div>
                      <dt>Evento</dt>
                      <dd>
                        {formatDate(selected.starts_at, timeZone)} —{" "}
                        {formatDate(selected.ends_at, timeZone)}
                      </dd>
                    </div>
                    {selected.type !== "block" && (
                      <div>
                        <dt>Ocupación adicional</dt>
                        <dd>
                          Buffer previo {selected.buffer_before_minutes ?? 0} min · montaje{" "}
                          {selected.setup_minutes ?? 0} min · desmontaje{" "}
                          {selected.teardown_minutes ?? 0} min · buffer posterior{" "}
                          {selected.buffer_after_minutes ?? 0} min
                        </dd>
                      </div>
                    )}
                    {selected.reason && (
                      <div>
                        <dt>Razón</dt>
                        <dd>{selected.reason}</dd>
                      </div>
                    )}
                  </dl>
                  <div className="schedule-actions">
                    {selected.type === "hold" && capabilities.has("reservation:confirm") && (
                      <button
                        onClick={() => {
                          setMode("confirm");
                        }}
                      >
                        Confirmar
                      </button>
                    )}
                    {selected.type !== "block" &&
                      selected.is_blocking &&
                      capabilities.has("reservation:reschedule") && (
                        <button
                          onClick={() => {
                            setMode("reschedule");
                          }}
                        >
                          Reprogramar
                        </button>
                      )}
                    {selected.type !== "block" &&
                      selected.is_blocking &&
                      capabilities.has("reservation:cancel") && (
                        <button
                          onClick={() => {
                            setMode("cancel");
                          }}
                        >
                          Cancelar
                        </button>
                      )}
                    {selected.type === "block" &&
                      selected.status === "active" &&
                      capabilities.has("schedule:block") && (
                        <>
                          <button
                            onClick={() => {
                              setMode("cancel");
                            }}
                          >
                            Liberar
                          </button>
                          <button
                            onClick={() => {
                              setMode("block");
                            }}
                          >
                            Anular
                          </button>
                        </>
                      )}
                  </div>
                </>
              )}

              {(mode === "reschedule" || (mode === "block" && !selected)) && (
                <div className="schedule-form">
                  {mode === "block" && !selected && (
                    <label>
                      Alcance
                      <select
                        value={blockScope}
                        onChange={(event) => {
                          setBlockScope(event.target.value as "spaces" | "venue");
                        }}
                      >
                        <option value="spaces">Espacio seleccionado</option>
                        <option value="venue">Sede completa</option>
                      </select>
                    </label>
                  )}
                  <label>
                    {mode === "reschedule" ? "Nuevo espacio" : "Espacio"}
                    <select
                      value={targetSpaceId}
                      onChange={(event) => {
                        setTargetSpaceId(event.target.value);
                      }}
                    >
                      {spaces.map((space) => (
                        <option key={space.id} value={space.id}>
                          {space.venueName} · {space.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Inicio local
                    <input
                      type="datetime-local"
                      value={startsAtLocal}
                      onChange={(event) => {
                        setStartsAtLocal(event.target.value);
                      }}
                    />
                  </label>
                  <label>
                    Fin local
                    <input
                      type="datetime-local"
                      value={endsAtLocal}
                      onChange={(event) => {
                        setEndsAtLocal(event.target.value);
                      }}
                    />
                  </label>
                  <label>
                    Razón
                    <textarea
                      value={reason}
                      onChange={(event) => {
                        setReason(event.target.value);
                      }}
                      maxLength={500}
                    />
                  </label>
                  {mode === "reschedule" && selected && (
                    <div className="schedule-comparison">
                      <strong>Comparación</strong>
                      <p>
                        Anterior: {formatDate(selected.starts_at, timeZone)} · {selected.space_name}
                      </p>
                      <p>
                        Nueva: {startsAtLocal.replace("T", " ")} ·{" "}
                        {spaces.find((space) => space.id === targetSpaceId)?.name}
                      </p>
                      <small>
                        La cotización y sus precios no cambian. La preparación previa quedará
                        terminal y se creará otra desde el snapshot aceptado.
                      </small>
                    </div>
                  )}
                  <button
                    className="button"
                    disabled={saving || !reason.trim() || !targetSpaceId}
                    onClick={() => void (mode === "reschedule" ? reschedule() : createBlock())}
                  >
                    {saving
                      ? "Guardando…"
                      : mode === "reschedule"
                        ? "Confirmar reprogramación"
                        : "Crear bloqueo"}
                  </button>
                </div>
              )}

              {mode === "confirm" && selected && (
                <div className="schedule-form">
                  <label>
                    Monto recibido
                    <input
                      inputMode="decimal"
                      value={depositAmount}
                      onChange={(event) => {
                        setDepositAmount(event.target.value);
                      }}
                      placeholder={
                        capabilities.has("reservation:waive_deposit")
                          ? "Vacío para excepción"
                          : "0.00"
                      }
                    />
                  </label>
                  {depositAmount ? (
                    <label>
                      Referencia
                      <input
                        value={depositReference}
                        onChange={(event) => {
                          setDepositReference(event.target.value);
                        }}
                      />
                    </label>
                  ) : (
                    <label>
                      Razón de excepción
                      <textarea
                        value={reason}
                        onChange={(event) => {
                          setReason(event.target.value);
                        }}
                      />
                    </label>
                  )}
                  <button
                    className="button"
                    disabled={
                      saving ||
                      (depositAmount
                        ? !depositReference.trim()
                        : !capabilities.has("reservation:waive_deposit") || !reason.trim())
                    }
                    onClick={() => void confirmHold()}
                  >
                    {saving ? "Confirmando…" : "Confirmar reserva"}
                  </button>
                </div>
              )}

              {mode === "cancel" && selected && (
                <div className="schedule-form">
                  <label>
                    Razón obligatoria
                    <textarea
                      value={reason}
                      onChange={(event) => {
                        setReason(event.target.value);
                      }}
                      maxLength={500}
                    />
                  </label>
                  <button
                    className="button button--danger"
                    disabled={saving || !reason.trim()}
                    onClick={() =>
                      void (selected.type === "block"
                        ? terminateBlock("release")
                        : cancelReservation())
                    }
                  >
                    {saving
                      ? "Procesando…"
                      : selected.type === "block"
                        ? "Liberar bloqueo"
                        : "Cancelar reserva"}
                  </button>
                </div>
              )}

              {mode === "block" && selected?.type === "block" && (
                <div className="schedule-form">
                  <label>
                    Razón de anulación
                    <textarea
                      value={reason}
                      onChange={(event) => {
                        setReason(event.target.value);
                      }}
                      maxLength={500}
                    />
                  </label>
                  <button
                    className="button button--danger"
                    disabled={saving || !reason.trim()}
                    onClick={() => void terminateBlock("cancel")}
                  >
                    Anular bloqueo
                  </button>
                </div>
              )}

              {selected?.type !== "block" && history.length > 0 && (
                <section className="schedule-history" aria-labelledby="schedule-history-title">
                  <h3 id="schedule-history-title">Historia de agenda</h3>
                  <ol>
                    {history.map((event) => (
                      <li key={event.id}>
                        <strong>{scheduleEventLabels[event.kind] ?? event.kind}</strong>
                        <small>{formatDate(event.occurred_at, timeZone)}</small>
                        {event.reason && <p>{event.reason}</p>}
                      </li>
                    ))}
                  </ol>
                </section>
              )}
            </aside>
          )}
        </div>
      )}
    </section>
  );
}
