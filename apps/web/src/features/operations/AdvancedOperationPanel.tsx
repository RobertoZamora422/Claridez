import { useCallback, useMemo, useState } from "react";

import {
  ApiError,
  api,
  type AdvancedOperation,
  type OperationAssignee,
  type OperationEvent,
  type OperationalIncident,
} from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { message } from "../../shared/utilities";

const PHASE_LABELS = {
  setup: "Montaje real",
  execution: "Ejecución",
  teardown: "Desmontaje",
  post_event: "Postevento",
} as const;

function key() {
  return crypto.randomUUID();
}

function duration(value: number | null | undefined) {
  if (value === null || value === undefined) return "Sin dato observado";
  const minutes = Math.round(value / 60);
  return `${String(minutes)} min`;
}

function metricNumber(advanced: AdvancedOperation, name: string) {
  const value = advanced.metrics[name];
  return typeof value === "number" ? value : 0;
}

export function AdvancedOperationPanel({
  organizationId,
  detail,
  assignees,
  canManage,
  canExecute,
  canManageIncidents,
  canAuthorizeChanges,
  canManageEvidence,
  canClose,
  onPreparationReload,
}: {
  organizationId: string;
  detail: OperationEvent;
  assignees: OperationAssignee[];
  canManage: boolean;
  canExecute: boolean;
  canManageIncidents: boolean;
  canAuthorizeChanges: boolean;
  canManageEvidence: boolean;
  canClose: boolean;
  onPreparationReload: () => Promise<void>;
}) {
  const base = `/api/v1/organizations/${organizationId}/operations/events/${detail.reservation_id}`;
  const [advanced, setAdvanced] = useState<AdvancedOperation | null>(null);
  const [legacyAvailable, setLegacyAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [incidentDescription, setIncidentDescription] = useState("");
  const [incidentImpact, setIncidentImpact] = useState("");
  const [incidentType, setIncidentType] = useState("other_operational");
  const [incidentSeverity, setIncidentSeverity] = useState("medium");
  const [incidentResponsible, setIncidentResponsible] = useState("");
  const [incidentFollowUps, setIncidentFollowUps] = useState<Record<string, string>>({});
  const [incidentResponsibles, setIncidentResponsibles] = useState<Record<string, string>>({});
  const [changeScope, setChangeScope] = useState("verification");
  const [changeTarget, setChangeTarget] = useState("");
  const [changePayload, setChangePayload] = useState("{}");
  const [changeReason, setChangeReason] = useState("");
  const [changeImpact, setChangeImpact] = useState("");
  const [evidenceTargetKind, setEvidenceTargetKind] = useState("general");
  const [evidenceTargetId, setEvidenceTargetId] = useState(detail.reservation_id);
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const body = await api<AdvancedOperation>(`${base}/advanced/`);
      setAdvanced(body);
      setLegacyAvailable(false);
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 404) {
        setLegacyAvailable(true);
        setAdvanced(null);
      } else setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useInitialLoad(load);

  const persistIncidentCloseData = async (incident: OperationalIncident) => {
    let current = incident;
    const responsibleId =
      incidentResponsibles[incident.id] ?? incident.responsible_membership_id ?? "";
    const followUp = incidentFollowUps[incident.id] ?? incident.follow_up;
    if (responsibleId !== (current.responsible_membership_id ?? "")) {
      current = await api<OperationalIncident>(`${base}/incidents/${incident.id}/amend/`, {
        method: "POST",
        body: JSON.stringify({
          revision: current.revision,
          kind: "reassigned",
          impact: current.impact,
          follow_up: current.follow_up,
          responsible_membership_id: responsibleId || null,
          detail: "Responsable de seguimiento actualizado",
          idempotency_key: key(),
        }),
      });
    }
    if (followUp.trim() !== current.follow_up) {
      current = await api<OperationalIncident>(`${base}/incidents/${incident.id}/amend/`, {
        method: "POST",
        body: JSON.stringify({
          revision: current.revision,
          kind: "follow_up_updated",
          impact: current.impact,
          follow_up: followUp,
          responsible_membership_id: current.responsible_membership_id,
          detail: "Seguimiento explícito actualizado",
          idempotency_key: key(),
        }),
      });
    }
    return current;
  };

  const run = useCallback(
    async (action: () => Promise<unknown>, success: string) => {
      setBusy(true);
      setError("");
      try {
        await action();
        setNotice(success);
        await Promise.all([load(), onPreparationReload()]);
      } catch (caught: unknown) {
        setError(message(caught));
      } finally {
        setBusy(false);
      }
    },
    [load, onPreparationReload],
  );

  const factKeys = useMemo(
    () =>
      new Set(
        (advanced?.phase_facts ?? [])
          .filter((fact) => fact.corrects_id === null)
          .map((fact) => `${fact.phase}:${fact.fact_kind}`),
      ),
    [advanced],
  );

  if (loading) return <Loading label="Cargando operación avanzada…" />;
  if (legacyAvailable)
    return (
      <section className="operation-panel" aria-labelledby="advanced-operation-title">
        <h2 id="advanced-operation-title">Operación avanzada</h2>
        <p>
          Esta preparación nació antes del corte P13. No se le atribuyó una plantilla ni historia
          sintética.
        </p>
        {canManage ? (
          <button
            className="button"
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  api(`${base}/advanced/adopt-legacy/`, {
                    method: "POST",
                    body: JSON.stringify({
                      revision: detail.preparation.revision,
                      idempotency_key: key(),
                    }),
                  }),
                "Preparación incorporada expresamente a P13.",
              )
            }
          >
            Incorporar estado observado a P13
          </button>
        ) : null}
        {error ? <Notice>{error}</Notice> : null}
      </section>
    );
  if (!advanced) return error ? <Notice>{error}</Notice> : null;

  return (
    <section className="operation-advanced" aria-labelledby="advanced-operation-title">
      <header className="operation-panel operation-advanced__header">
        <div>
          <p className="eyebrow">Plan congelado</p>
          <h2 id="advanced-operation-title">Operación avanzada</h2>
          <p>
            {advanced.snapshot.source_version} · {advanced.snapshot.source_kind}
          </p>
        </div>
        {advanced.close ? <StatusBadge value="completed" /> : <StatusBadge value="active" />}
      </header>
      {notice ? <p className="success-message">{notice}</p> : null}
      {error ? <Notice>{error}</Notice> : null}

      <section className="operation-panel" aria-labelledby="metrics-title">
        <h3 id="metrics-title">Métricas operativas</h3>
        <div className="operation-metrics">
          <span>
            <strong>Readiness</strong>
            {duration(advanced.metrics.readiness_seconds as number | null)}
          </span>
          <span>
            <strong>Montaje</strong>
            {duration(advanced.metrics.setup_seconds as number | null)}
          </span>
          <span>
            <strong>Ejecución</strong>
            {duration(advanced.metrics.execution_seconds as number | null)}
          </span>
          <span>
            <strong>Desmontaje</strong>
            {duration(advanced.metrics.teardown_seconds as number | null)}
          </span>
          <span>
            <strong>Incidencias</strong>
            {String(metricNumber(advanced, "incident_count"))}
          </span>
          <span>
            <strong>Cambios autorizados</strong>
            {String(metricNumber(advanced, "authorized_change_count"))}
          </span>
        </div>
      </section>

      <section className="operation-panel" aria-labelledby="phase-verifications-title">
        <h3 id="phase-verifications-title">Verificaciones por fase</h3>
        {(Object.keys(PHASE_LABELS) as (keyof typeof PHASE_LABELS)[]).map((phase) => {
          const rows = advanced.verifications.filter((item) => item.phase === phase);
          if (rows.length === 0) return null;
          return (
            <div className="operation-phase" key={phase}>
              <h4>{PHASE_LABELS[phase]}</h4>
              <ul className="operation-compact-list">
                {rows.map((item) => (
                  <li key={item.id}>
                    <span>
                      <strong>{item.title}</strong>
                      {item.is_required ? " · obligatoria" : ""}
                    </span>
                    <StatusBadge value={item.status} />
                    {canExecute && item.status === "pending" ? (
                      <span className="operation-inline-actions">
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () =>
                                api(`${base}/verifications/${item.id}/`, {
                                  method: "PUT",
                                  body: JSON.stringify({
                                    revision: item.revision,
                                    status: "completed",
                                    reason: "",
                                    idempotency_key: key(),
                                  }),
                                }),
                              "Verificación completada.",
                            )
                          }
                        >
                          Completar
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => {
                            const reason = window.prompt("Razón para no aplica");
                            if (reason)
                              void run(
                                () =>
                                  api(`${base}/verifications/${item.id}/`, {
                                    method: "PUT",
                                    body: JSON.stringify({
                                      revision: item.revision,
                                      status: "not_applicable",
                                      reason,
                                      idempotency_key: key(),
                                    }),
                                  }),
                                "Verificación justificada como no aplicable.",
                              );
                          }}
                        >
                          No aplica
                        </button>
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </section>

      <section className="operation-panel" aria-labelledby="observed-work-title">
        <h3 id="observed-work-title">Trabajo observado</h3>
        <p>Estos hechos no modifican la ocupación autorizada por Agenda.</p>
        {(["setup", "teardown"] as const).map((phase) => (
          <div className="operation-phase-actions" key={phase}>
            <strong>{PHASE_LABELS[phase]}</strong>
            {(["started", "completed"] as const).map((factKind) => (
              <button
                key={factKind}
                disabled={busy || factKeys.has(`${phase}:${factKind}`) || !canExecute}
                onClick={() =>
                  void run(
                    () =>
                      api(`${base}/phase-facts/`, {
                        method: "POST",
                        body: JSON.stringify({
                          revision: detail.preparation.revision,
                          phase,
                          fact_kind: factKind,
                          idempotency_key: key(),
                        }),
                      }),
                    `${PHASE_LABELS[phase]} ${factKind === "started" ? "iniciado" : "finalizado"}.`,
                  )
                }
              >
                {factKind === "started" ? "Registrar inicio" : "Registrar finalización"}
              </button>
            ))}
          </div>
        ))}
      </section>

      {advanced.snapshot.roles.length > 0 ? (
        <section className="operation-panel" aria-labelledby="roles-title">
          <h3 id="roles-title">Responsabilidades del evento</h3>
          {advanced.snapshot.roles.map((role) => {
            const assigned = advanced.responsibilities.find(
              (item) => item.role_key === role.key && item.phase === role.phase,
            );
            return (
              <label key={`${role.key}:${role.phase}`}>
                {role.label} {role.phase ? `· ${role.phase}` : ""}
                <select
                  disabled={!canManage || busy}
                  value={assigned?.membership_id ?? ""}
                  onChange={(event) =>
                    void run(
                      () =>
                        api(`${base}/responsibilities/`, {
                          method: "POST",
                          body: JSON.stringify({
                            revision: detail.preparation.revision,
                            role_key: role.key,
                            phase: role.phase,
                            membership_id: event.target.value || null,
                            idempotency_key: key(),
                          }),
                        }),
                      "Responsabilidad actualizada.",
                    )
                  }
                >
                  <option value="">Sin asignar</option>
                  {assignees.map((assignee) => (
                    <option key={assignee.membership_id} value={assignee.membership_id}>
                      {assignee.display_name}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
        </section>
      ) : null}

      <section className="operation-panel" aria-labelledby="incidents-title">
        <h3 id="incidents-title">Incidencias</h3>
        <ul className="operation-compact-list">
          {advanced.incidents.map((incident) => {
            const responsibleId =
              incidentResponsibles[incident.id] ?? incident.responsible_membership_id ?? "";
            const followUp = incidentFollowUps[incident.id] ?? incident.follow_up;
            return (
              <li key={incident.id}>
                <span>
                  <strong>{incident.description}</strong> · {incident.severity} · {incident.impact}
                </span>
                <span>
                  Seguimiento: {incident.follow_up || "pendiente"} · Responsable:{" "}
                  {assignees.find(
                    (assignee) => assignee.membership_id === incident.responsible_membership_id,
                  )?.display_name ?? "sin asignar"}
                </span>
                <StatusBadge value={incident.status} />
                {canManageIncidents && incident.status !== "resolved" ? (
                  <div className="operation-grid-form">
                    <label>
                      Seguimiento explícito
                      <input
                        aria-label={`Seguimiento para ${incident.description}`}
                        value={followUp}
                        onChange={(event) => {
                          setIncidentFollowUps((current) => ({
                            ...current,
                            [incident.id]: event.target.value,
                          }));
                        }}
                      />
                    </label>
                    <label>
                      Responsable del seguimiento
                      <select
                        aria-label={`Responsable para ${incident.description}`}
                        value={responsibleId}
                        onChange={(event) => {
                          setIncidentResponsibles((current) => ({
                            ...current,
                            [incident.id]: event.target.value,
                          }));
                        }}
                      >
                        <option value="">Sin asignar</option>
                        {assignees.map((assignee) => (
                          <option key={assignee.membership_id} value={assignee.membership_id}>
                            {assignee.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <span className="operation-inline-actions">
                      {incident.status === "open" ? (
                        <button
                          disabled={busy || !responsibleId || !followUp.trim()}
                          onClick={() =>
                            void run(async () => {
                              const current = await persistIncidentCloseData(incident);
                              return api(`${base}/incidents/${incident.id}/transition/`, {
                                method: "POST",
                                body: JSON.stringify({
                                  revision: current.revision,
                                  status: "contained",
                                  detail: "Contención registrada",
                                  follow_up: followUp,
                                  idempotency_key: key(),
                                }),
                              });
                            }, "Incidencia contenida.")
                          }
                        >
                          Contener
                        </button>
                      ) : (
                        <button
                          disabled={busy || !responsibleId || !followUp.trim()}
                          onClick={() =>
                            void run(
                              () => persistIncidentCloseData(incident),
                              "Seguimiento de incidencia actualizado.",
                            )
                          }
                        >
                          Guardar seguimiento
                        </button>
                      )}
                      <button
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () =>
                              api(`${base}/incidents/${incident.id}/transition/`, {
                                method: "POST",
                                body: JSON.stringify({
                                  revision: incident.revision,
                                  status: "resolved",
                                  detail: "Corrección aplicada",
                                  follow_up: "",
                                  idempotency_key: key(),
                                }),
                              }),
                            "Incidencia resuelta.",
                          )
                        }
                      >
                        Resolver
                      </button>
                    </span>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
        {canManageIncidents ? (
          <form
            className="operation-grid-form"
            onSubmit={(event) => {
              event.preventDefault();
              void run(
                () =>
                  api(`${base}/incidents/`, {
                    method: "POST",
                    body: JSON.stringify({
                      incident_type: incidentType,
                      severity: incidentSeverity,
                      description: incidentDescription,
                      impact: incidentImpact,
                      responsible_membership_id: incidentResponsible || null,
                      idempotency_key: key(),
                    }),
                  }),
                "Incidencia registrada.",
              );
            }}
          >
            <h4>Nueva incidencia</h4>
            <select
              value={incidentType}
              onChange={(event) => {
                setIncidentType(event.target.value);
              }}
              aria-label="Tipo de incidencia"
            >
              <option value="safety">Seguridad</option>
              <option value="schedule_or_space">Agenda o espacio</option>
              <option value="resource">Recurso</option>
              <option value="supplier">Proveedor</option>
              <option value="service_quality">Calidad de servicio</option>
              <option value="customer_scope">Alcance cliente</option>
              <option value="other_operational">Otra operativa</option>
            </select>
            <select
              value={incidentSeverity}
              onChange={(event) => {
                setIncidentSeverity(event.target.value);
              }}
              aria-label="Severidad"
            >
              <option value="low">Baja</option>
              <option value="medium">Media</option>
              <option value="high">Alta</option>
              <option value="critical">Crítica</option>
            </select>
            <input
              required
              placeholder="Descripción"
              value={incidentDescription}
              onChange={(event) => {
                setIncidentDescription(event.target.value);
              }}
            />
            <label>
              Responsable inicial (opcional)
              <select
                value={incidentResponsible}
                onChange={(event) => {
                  setIncidentResponsible(event.target.value);
                }}
              >
                <option value="">Sin asignar</option>
                {assignees.map((assignee) => (
                  <option key={assignee.membership_id} value={assignee.membership_id}>
                    {assignee.display_name}
                  </option>
                ))}
              </select>
            </label>
            <input
              required
              placeholder="Impacto"
              value={incidentImpact}
              onChange={(event) => {
                setIncidentImpact(event.target.value);
              }}
            />
            <button className="button" disabled={busy}>
              Registrar incidencia
            </button>
          </form>
        ) : null}
      </section>

      <section className="operation-panel" aria-labelledby="resources-title">
        <h3 id="resources-title">Recursos por ventana operacional</h3>
        <ul className="operation-compact-list">
          {advanced.resource_windows.map((window_) => {
            const requirement = advanced.resources.find(
              (item) => item.operational_window_id === window_.id,
            );
            return (
              <li key={window_.id}>
                <span>
                  {window_.quantity} · {new Date(window_.starts_at).toLocaleString()} —{" "}
                  {new Date(window_.ends_at).toLocaleString()}
                </span>
                {requirement ? (
                  <StatusBadge value={requirement.status} />
                ) : canManage ? (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api(`${base}/windows/${window_.id}/reserve/`, {
                            method: "POST",
                            body: JSON.stringify({
                              reason: "Necesidad del plan operativo",
                              idempotency_key: key(),
                            }),
                          }),
                        "Necesidad entregada a Recursos.",
                      )
                    }
                  >
                    Solicitar a Recursos
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
        {advanced.resources.map((resource) => (
          <p key={resource.id}>
            <strong>{resource.resource_name}</strong> · {resource.status} ·{" "}
            {resource.supplier_names.join(", ") || "sin proveedor"}
          </p>
        ))}
      </section>

      <details className="operation-panel">
        <summary>Cambios autorizados</summary>
        <ul className="operation-compact-list">
          {advanced.changes.map((change) => (
            <li key={change.id}>
              <span>
                <strong>{change.scope}</strong> · {change.reason} · {change.impact}
              </span>
              <StatusBadge value={change.status} />
              {canAuthorizeChanges && change.status === "pending" ? (
                <span className="operation-inline-actions">
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api(`${base}/changes/${change.id}/decide/`, {
                            method: "POST",
                            body: JSON.stringify({
                              revision: detail.preparation.revision,
                              approved: true,
                              reason: "Cambio autorizado",
                              idempotency_key: key(),
                            }),
                          }),
                        "Cambio autorizado.",
                      )
                    }
                  >
                    Autorizar
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api(`${base}/changes/${change.id}/decide/`, {
                            method: "POST",
                            body: JSON.stringify({
                              revision: detail.preparation.revision,
                              approved: false,
                              reason: "Cambio rechazado",
                              idempotency_key: key(),
                            }),
                          }),
                        "Cambio rechazado.",
                      )
                    }
                  >
                    Rechazar
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        {canManage ? (
          <form
            className="operation-grid-form"
            onSubmit={(event) => {
              event.preventDefault();
              let proposed: Record<string, unknown>;
              try {
                proposed = JSON.parse(changePayload) as Record<string, unknown>;
              } catch {
                setError("El contenido propuesto debe ser JSON válido.");
                return;
              }
              void run(
                () =>
                  api(`${base}/changes/`, {
                    method: "POST",
                    body: JSON.stringify({
                      revision: detail.preparation.revision,
                      scope: changeScope,
                      target_id: changeTarget,
                      proposed_payload: proposed,
                      reason: changeReason,
                      impact: changeImpact,
                      idempotency_key: key(),
                    }),
                  }),
                "Cambio propuesto para autorización.",
              );
            }}
          >
            <select
              value={changeScope}
              onChange={(event) => {
                setChangeScope(event.target.value);
              }}
              aria-label="Alcance del cambio"
            >
              <option value="readiness">Readiness</option>
              <option value="verification">Verificación</option>
              <option value="responsibility">Responsabilidad</option>
              <option value="resource_need">Necesidad de recurso</option>
              <option value="resource_window">Ventana de recurso</option>
            </select>
            <input
              required
              placeholder="Identidad del objetivo"
              value={changeTarget}
              onChange={(event) => {
                setChangeTarget(event.target.value);
              }}
            />
            <textarea
              required
              aria-label="Contenido propuesto JSON"
              value={changePayload}
              onChange={(event) => {
                setChangePayload(event.target.value);
              }}
            />
            <input
              required
              placeholder="Razón"
              value={changeReason}
              onChange={(event) => {
                setChangeReason(event.target.value);
              }}
            />
            <input
              required
              placeholder="Impacto"
              value={changeImpact}
              onChange={(event) => {
                setChangeImpact(event.target.value);
              }}
            />
            <button className="button" disabled={busy}>
              Proponer cambio
            </button>
          </form>
        ) : null}
      </details>

      <section className="operation-panel" aria-labelledby="evidence-title">
        <h3 id="evidence-title">Evidencia privada</h3>
        <ul className="operation-compact-list">
          {advanced.evidence.map((item) => (
            <li key={item.id}>
              <span>
                {item.target_kind} · {new Date(item.created_at).toLocaleString()}
              </span>
              <a href={`${base}/evidence/${item.document_file_id}/download/`}>Descargar</a>
            </li>
          ))}
        </ul>
        {canManageEvidence ? (
          <form
            className="operation-grid-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!evidenceFile) return;
              const form = new FormData();
              form.set("target_kind", evidenceTargetKind);
              form.set(
                "target_id",
                evidenceTargetKind === "general" ? detail.reservation_id : evidenceTargetId,
              );
              form.set("display_name", evidenceFile.name);
              form.set("declared_media_type", evidenceFile.type || "application/octet-stream");
              form.set("correlation_id", key());
              form.set("idempotency_key", key());
              form.set("file", evidenceFile);
              void run(
                () => api(`${base}/evidence/`, { method: "POST", body: form }),
                "Evidencia enviada a Documents.",
              );
            }}
          >
            <select
              value={evidenceTargetKind}
              onChange={(event) => {
                setEvidenceTargetKind(event.target.value);
              }}
              aria-label="Destino de evidencia"
            >
              <option value="general">General</option>
              <option value="verification">Verificación</option>
              <option value="incident">Incidencia</option>
              <option value="change">Cambio</option>
              <option value="close">Cierre</option>
            </select>
            {evidenceTargetKind !== "general" ? (
              <input
                required
                placeholder="Identidad del destino"
                value={evidenceTargetId}
                onChange={(event) => {
                  setEvidenceTargetId(event.target.value);
                }}
              />
            ) : null}
            <input
              required
              type="file"
              onChange={(event) => {
                setEvidenceFile(event.target.files?.[0] ?? null);
              }}
            />
            <button className="button" disabled={busy}>
              Adjuntar evidencia
            </button>
          </form>
        ) : null}
      </section>

      {detail.preparation.status === "completed" ? (
        <section className="operation-panel" aria-labelledby="post-close-title">
          <h3 id="post-close-title">Cierre postevento</h3>
          {advanced.close ? (
            <p>
              Cerrado el {new Date(advanced.close.closed_at).toLocaleString()} sin alterar el estado
              completed.
            </p>
          ) : canClose ? (
            <>
              {advanced.incidents.some(
                (incident) =>
                  incident.status === "open" ||
                  (incident.status === "contained" &&
                    (incident.severity === "high" ||
                      incident.severity === "critical" ||
                      !incident.responsible_membership_id ||
                      !incident.impact.trim() ||
                      !incident.follow_up.trim())),
              ) ? (
                <p>Completa o resuelve las incidencias incompatibles antes de cerrar.</p>
              ) : null}
              <button
                className="button"
                disabled={
                  busy ||
                  advanced.incidents.some(
                    (incident) =>
                      incident.status === "open" ||
                      (incident.status === "contained" &&
                        (incident.severity === "high" ||
                          incident.severity === "critical" ||
                          !incident.responsible_membership_id ||
                          !incident.impact.trim() ||
                          !incident.follow_up.trim())),
                  )
                }
                onClick={() =>
                  void run(
                    () =>
                      api(`${base}/close/`, {
                        method: "POST",
                        body: JSON.stringify({
                          revision: detail.preparation.revision,
                          idempotency_key: key(),
                        }),
                      }),
                    "Cierre postevento registrado.",
                  )
                }
              >
                Cerrar postevento
              </button>
            </>
          ) : (
            <p>El cierre está pendiente.</p>
          )}
        </section>
      ) : null}
    </section>
  );
}
