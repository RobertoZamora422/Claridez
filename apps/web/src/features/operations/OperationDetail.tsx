import { useMemo } from "react";

import type { OperationAssignee, OperationEvent, PreparationItem } from "../../api";
import { Notice } from "../../shared/components";
import { SECTION_LABELS, STATUS_LABELS } from "./constants";
import { ItemEditor } from "./ItemEditor";
import { NewItemForm } from "./NewItemForm";
import { localDate, readinessBlockers, reorderTargets } from "./operationHelpers";
import { PreparationNotes } from "./PreparationNotes";

export function OperationDetail({
  detail,
  base,
  assignees,
  canManage,
  canExecute,
  notice,
  error,
  onBack,
  onAssign,
  onCommand,
  onReload,
  onReplace,
  onItemUpdated,
}: {
  detail: OperationEvent;
  base: string;
  assignees: OperationAssignee[];
  canManage: boolean;
  canExecute: boolean;
  notice: string;
  error: string;
  onBack: () => void;
  onAssign: (membershipId: string) => Promise<void>;
  onCommand: (command: "ready" | "start" | "complete") => Promise<void>;
  onReload: () => Promise<void>;
  onReplace: (updated: OperationEvent, notice: string) => void;
  onItemUpdated: (item: PreparationItem, preparationRevision: number, status?: string) => void;
}) {
  const groupedItems = useMemo(() => {
    const groups: Record<PreparationItem["section"], PreparationItem[]> = {
      definitions: [],
      setup: [],
      final_review: [],
    };
    for (const item of detail.preparation.items ?? []) groups[item.section].push(item);
    return groups;
  }, [detail]);
  const blockers = useMemo(() => readinessBlockers(detail), [detail]);
  const frozen = ["in_progress", "completed", "cancelled"].includes(detail.preparation.status);

  return (
    <section aria-labelledby="operation-detail-title">
      <button className="back-button" onClick={onBack}>
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
                if (event.target.value) void onAssign(event.target.value);
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
            onReplace(updated, "Notas operativas actualizadas.");
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
          <NewItemForm event={detail} base={base} onCreated={onReload} />
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
                    onReload={onReload}
                    onUpdated={onItemUpdated}
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
            {blockers.length > 0 ? (
              <div className="readiness-blockers" role="status">
                <strong>Antes de declarar listo:</strong>
                <ul>
                  {blockers.map((blocker) => (
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
              disabled={blockers.length > 0}
              onClick={() => {
                void onCommand("ready");
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
              void onCommand("start");
            }}
          >
            Iniciar ejecución
          </button>
        ) : null}
        {canExecute && detail.preparation.status === "in_progress" ? (
          <button
            className="button"
            onClick={() => {
              void onCommand("complete");
            }}
          >
            Completar evento
          </button>
        ) : null}
      </div>
    </section>
  );
}
