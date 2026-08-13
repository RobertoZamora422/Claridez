import { useCallback, useMemo, useState } from "react";

import { api } from "../../api";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { formText, message } from "../../shared/utilities";

interface TemplateVersion {
  id: string;
  version: number;
  status: "draft" | "published" | "inactive";
  title: string;
  body_html: string;
  variable_schema: {
    version: string;
    variables: { name: string; required: boolean; fallback?: string }[];
  };
}
interface Template {
  id: string;
  name: string;
  is_active: boolean;
  versions: TemplateVersion[];
}
interface Grant {
  id: string;
  purpose: string;
  expires_at: string;
  revoked_at: string | null;
}
interface IssuedVersion {
  id: string;
  version: number;
  state: string;
  snapshot_sha256: string;
  artifact: {
    id: string;
    sha256: string;
    size_bytes: number;
    state: string;
    verified_at: string | null;
  } | null;
  acceptance: { accepted_at: string; artifact_sha256: string } | null;
  grants: Grant[];
}
interface Instrument {
  id: string;
  instrument_type: string;
  title: string;
  status: string;
  versions: IssuedVersion[];
}
interface ExternalFile {
  id: string;
  display_name: string;
  media_type: string;
  state: string;
  validation_detail: string;
}
interface RecordState {
  status: string;
  label?: string;
  id?: string;
  root_reservation_id: string;
  instruments: Instrument[];
  external_files: ExternalFile[];
}
interface RetentionData {
  policies: {
    id: string;
    key: string;
    version: number;
    name: string;
    classification: string;
    status: string;
  }[];
  assignments: {
    id: string;
    policy_id: string;
    target_type: string;
    target_id: string;
    state: string;
    eligible_at: string | null;
  }[];
  holds: {
    id: string;
    assignment_id: string;
    reason: string;
    placed_at: string;
    released_at: string | null;
  }[];
}

const DEFAULT_BODY = `<h1>{{ organization.name }}</h1><h2>Contrato para {{ counterparty.full_name }}</h2><p>Reserva: {{ reservation.starts_at }} a {{ reservation.ends_at }}</p><p>Espacio: {{ reservation.venue_name }} — {{ reservation.space_name }}</p>{{ quotation.lines_table }}<p><strong>Total: {{ quotation.currency }} {{ quotation.total }}</strong></p>`;
const DEFAULT_SCHEMA = {
  version: "claridez-vars-v1",
  variables: [
    "organization.name",
    "counterparty.full_name",
    "reservation.starts_at",
    "reservation.ends_at",
    "reservation.venue_name",
    "reservation.space_name",
    "quotation.lines_table",
    "quotation.currency",
    "quotation.total",
  ].map((name) => ({ name, required: true })),
};

export function DocumentsView({
  organizationId,
  capabilities,
}: {
  organizationId: string;
  capabilities: Set<string>;
}) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [record, setRecord] = useState<RecordState | null>(null);
  const [retention, setRetention] = useState<RetentionData | null>(null);
  const [rootId, setRootId] = useState("");
  const [previewHtml, setPreviewHtml] = useState("");
  const [externalLink, setExternalLink] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canManageTemplates = capabilities.has("document_template:manage");
  const canIssue = capabilities.has("contractual_instrument:issue");
  const canFiles = capabilities.has("document_external_file:manage");
  const canGrants = capabilities.has("document_external_access:manage");
  const canRetention = capabilities.has("document_retention:manage");
  const publishedVersions = useMemo(
    () =>
      templates.flatMap((template) =>
        template.versions.filter((version) => version.status === "published" && template.is_active),
      ),
    [templates],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [templateBody, retentionBody] = await Promise.all([
        api<{ templates: Template[] }>(
          `/api/v1/organizations/${organizationId}/documents/templates/`,
        ),
        capabilities.has("document_retention:read")
          ? api<RetentionData>(`/api/v1/organizations/${organizationId}/documents/retention/`)
          : Promise.resolve(null),
      ]);
      setTemplates(templateBody.templates);
      setRetention(retentionBody);
      setError("");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [capabilities, organizationId]);
  useInitialLoad(load);

  async function mutate(operation: () => Promise<unknown>, reloadRecord = false) {
    setBusy(true);
    setError("");
    try {
      await operation();
      await load();
      if (reloadRecord && rootId) await lookupRecord(rootId);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }
  async function lookupRecord(value: string) {
    const body = await api<RecordState>(
      `/api/v1/organizations/${organizationId}/documents/records/?root_reservation_id=${encodeURIComponent(value)}`,
    );
    setRecord(body);
    setRootId(value);
  }

  if (loading) return <Loading label="Cargando contratos y documentos…" />;
  return (
    <section className="documents-page" aria-labelledby="documents-title">
      <header className="page-header">
        <div>
          <p className="eyebrow">P9 · Evidencia documental</p>
          <h1 id="documents-title">Contratos y documentos</h1>
          <p className="muted">
            Plantillas versionadas, emisiones inmutables, archivos privados y aceptación vinculada a
            bytes exactos.
          </p>
        </div>
      </header>
      {error && <Notice>{error}</Notice>}

      <section className="panel form-stack" aria-labelledby="record-search-title">
        <h2 id="record-search-title">Expediente por raíz de reserva</h2>
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const value = formText(new FormData(event.currentTarget), "root_id");
            void mutate(() => lookupRecord(value));
          }}
        >
          <label>
            UUID de reserva raíz
            <input name="root_id" defaultValue={rootId} required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Consultar
          </button>
        </form>
        {record ? (
          <RecordPanel
            organizationId={organizationId}
            record={record}
            templates={publishedVersions}
            busy={busy}
            canIssue={canIssue}
            canFiles={canFiles}
            canGrants={canGrants}
            onMutate={(operation) => {
              void mutate(operation, true);
            }}
            onExternalLink={setExternalLink}
          />
        ) : (
          <p className="muted">
            Consulta una raíz para ver su estado documental. Una reserva histórica puede aparecer
            honestamente sin contrato emitido.
          </p>
        )}
        {externalLink ? (
          <Notice tone="info">
            Enlace mostrado una sola vez: <a href={externalLink}>{externalLink}</a>
          </Notice>
        ) : null}
      </section>

      <section className="panel form-stack" aria-labelledby="templates-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Lenguaje cerrado</p>
            <h2 id="templates-title">Plantillas y versiones</h2>
          </div>
        </div>
        {canManageTemplates ? (
          <TemplateCreateForm
            busy={busy}
            onCreate={(data) => {
              void mutate(() =>
                api(`/api/v1/organizations/${organizationId}/documents/templates/`, {
                  method: "POST",
                  body: JSON.stringify(data),
                }),
              );
            }}
          />
        ) : null}
        <div className="document-grid">
          {templates.map((template) => (
            <article className="document-card" key={template.id}>
              <div className="panel-header">
                <h3>{template.name}</h3>
                <StatusBadge value={template.is_active ? "active" : "inactive"} />
              </div>
              <div className="button-row">
                {canManageTemplates ? (
                  <button
                    className="button button--ghost"
                    disabled={busy}
                    onClick={() =>
                      void mutate(() =>
                        api(
                          `/api/v1/organizations/${organizationId}/documents/templates/${template.id}/active/`,
                          {
                            method: "PATCH",
                            body: JSON.stringify({ active: !template.is_active }),
                          },
                        ),
                      )
                    }
                  >
                    {template.is_active ? "Inactivar plantilla" : "Reactivar plantilla"}
                  </button>
                ) : null}
                {canManageTemplates &&
                !template.versions.some((version) => version.status === "draft") &&
                template.versions.length ? (
                  <button
                    className="button button--secondary"
                    disabled={busy}
                    onClick={() => {
                      const source = [...template.versions].sort(
                        (left, right) => right.version - left.version,
                      )[0];
                      if (!source) return;
                      void mutate(() =>
                        api(
                          `/api/v1/organizations/${organizationId}/documents/templates/${template.id}/versions/`,
                          {
                            method: "POST",
                            body: JSON.stringify({
                              title: source.title,
                              body_html: source.body_html,
                              variable_schema: source.variable_schema,
                            }),
                          },
                        ),
                      );
                    }}
                  >
                    Crear siguiente borrador
                  </button>
                ) : null}
              </div>
              {template.versions.map((version) => (
                <div className="document-version" key={version.id}>
                  <span>
                    v{version.version} · {version.title}
                  </span>
                  <StatusBadge value={version.status} />
                  <div className="button-row">
                    {rootId && version.status !== "inactive" && canIssue ? (
                      <button
                        className="button button--ghost"
                        onClick={() =>
                          void mutate(async () => {
                            const result = await api<{ html: string }>(
                              `/api/v1/organizations/${organizationId}/documents/preview/`,
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  root_reservation_id: rootId,
                                  template_version_id: version.id,
                                }),
                              },
                            );
                            setPreviewHtml(result.html);
                          })
                        }
                      >
                        Preview
                      </button>
                    ) : null}
                    {canManageTemplates && version.status === "draft" ? (
                      <button
                        className="button button--secondary"
                        onClick={() =>
                          void mutate(() =>
                            api(
                              `/api/v1/organizations/${organizationId}/documents/template-versions/${version.id}/publish/`,
                              { method: "POST" },
                            ),
                          )
                        }
                      >
                        Publicar
                      </button>
                    ) : null}
                    {canManageTemplates && version.status === "published" ? (
                      <button
                        className="button button--ghost"
                        onClick={() =>
                          void mutate(() =>
                            api(
                              `/api/v1/organizations/${organizationId}/documents/template-versions/${version.id}/inactivate/`,
                              { method: "POST" },
                            ),
                          )
                        }
                      >
                        Inactivar versión
                      </button>
                    ) : null}
                  </div>
                  {canManageTemplates && version.status === "draft" ? (
                    <form
                      className="form-stack template-editor"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const form = new FormData(event.currentTarget);
                        try {
                          const variableSchema: unknown = JSON.parse(
                            formText(form, "variable_schema"),
                          );
                          void mutate(() =>
                            api(
                              `/api/v1/organizations/${organizationId}/documents/template-versions/${version.id}/`,
                              {
                                method: "PATCH",
                                body: JSON.stringify({
                                  title: formText(form, "title"),
                                  body_html: formText(form, "body_html"),
                                  variable_schema: variableSchema,
                                }),
                              },
                            ),
                          );
                        } catch {
                          setError("La declaración de variables no contiene JSON válido.");
                        }
                      }}
                    >
                      <label>
                        Título
                        <input name="title" defaultValue={version.title} required />
                      </label>
                      <label>
                        HTML restringido
                        <textarea name="body_html" rows={6} defaultValue={version.body_html} />
                      </label>
                      <label>
                        Variables
                        <textarea
                          name="variable_schema"
                          rows={6}
                          defaultValue={JSON.stringify(version.variable_schema, null, 2)}
                        />
                      </label>
                      <button className="button button--ghost" disabled={busy}>
                        Guardar borrador
                      </button>
                    </form>
                  ) : null}
                </div>
              ))}
            </article>
          ))}
        </div>
        {previewHtml ? (
          <div className="preview-shell">
            <strong>VISTA PREVIA — NO CONTRACTUAL</strong>
            <iframe sandbox="" title="Vista previa no contractual" srcDoc={previewHtml} />
          </div>
        ) : null}
      </section>

      {retention ? (
        <RetentionPanel
          organizationId={organizationId}
          data={retention}
          canManage={canRetention}
          busy={busy}
          onMutate={(operation) => {
            void mutate(operation);
          }}
        />
      ) : null}
    </section>
  );
}

function TemplateCreateForm({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (data: object) => void;
}) {
  return (
    <form
      className="form-stack template-editor"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        try {
          const variableSchema: unknown = JSON.parse(formText(data, "variable_schema"));
          onCreate({
            name: formText(data, "name"),
            title: formText(data, "title"),
            body_html: formText(data, "body_html"),
            variable_schema: variableSchema,
          });
          event.currentTarget.reset();
        } catch {
          /* JSON remains visibly editable */
        }
      }}
    >
      <div className="form-grid">
        <label>
          Nombre lógico
          <input name="name" required />
        </label>
        <label>
          Título emitido
          <input name="title" required />
        </label>
      </div>
      <label>
        HTML restringido
        <textarea name="body_html" rows={7} defaultValue={DEFAULT_BODY} required />
      </label>
      <label>
        Declaración JSON de variables
        <textarea
          name="variable_schema"
          rows={8}
          defaultValue={JSON.stringify(DEFAULT_SCHEMA, null, 2)}
          required
        />
      </label>
      <button className="button button--primary" disabled={busy}>
        Crear plantilla y borrador v1
      </button>
    </form>
  );
}

function RecordPanel({
  organizationId,
  record,
  templates,
  busy,
  canIssue,
  canFiles,
  canGrants,
  onMutate,
  onExternalLink,
}: {
  organizationId: string;
  record: RecordState;
  templates: TemplateVersion[];
  busy: boolean;
  canIssue: boolean;
  canFiles: boolean;
  canGrants: boolean;
  onMutate: (operation: () => Promise<unknown>) => void;
  onExternalLink: (link: string) => void;
}) {
  const recordId = record.id;
  if (!recordId)
    return (
      <div className="empty-state">
        <h3>Sin contrato emitido</h3>
        <p>No existe un expediente ficticio para esta reserva.</p>
        {canIssue ? (
          <button
            className="button button--primary"
            disabled={busy}
            onClick={() => {
              onMutate(() =>
                api(`/api/v1/organizations/${organizationId}/documents/records/`, {
                  method: "POST",
                  body: JSON.stringify({ root_reservation_id: record.root_reservation_id }),
                }),
              );
            }}
          >
            Crear expediente
          </button>
        ) : null}
      </div>
    );
  return (
    <div className="form-stack">
      <div className="panel-header">
        <h3>{record.label ?? "Expediente contractual"}</h3>
        <code>{record.id}</code>
      </div>
      {canIssue ? (
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            onMutate(() =>
              api(
                `/api/v1/organizations/${organizationId}/documents/records/${recordId}/instruments/`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    instrument_type: formText(data, "instrument_type"),
                    title: formText(data, "title"),
                  }),
                },
              ),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Tipo
            <select name="instrument_type">
              <option value="main_contract">Contrato principal</option>
              <option value="addendum">Adenda</option>
              <option value="termination">Terminación</option>
              <option value="annex">Anexo</option>
              <option value="other">Otro aprobado</option>
            </select>
          </label>
          <label>
            Título
            <input name="title" required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Crear instrumento
          </button>
        </form>
      ) : null}
      {record.instruments.map((instrument) => (
        <article className="document-card" key={instrument.id}>
          <div className="panel-header">
            <div>
              <h3>{instrument.title}</h3>
              <small>{instrument.instrument_type}</small>
            </div>
            <StatusBadge value={instrument.status} />
          </div>
          {canIssue && templates.length ? (
            <form
              className="compact-form"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                onMutate(() =>
                  api(
                    `/api/v1/organizations/${organizationId}/documents/instruments/${instrument.id}/issue/`,
                    {
                      method: "POST",
                      headers: { "Idempotency-Key": crypto.randomUUID() },
                      body: JSON.stringify({ template_version_id: formText(data, "template") }),
                    },
                  ),
                );
              }}
            >
              <label>
                Plantilla publicada
                <select name="template">
                  {templates.map((template) => (
                    <option value={template.id} key={template.id}>
                      {template.title} · v{template.version}
                    </option>
                  ))}
                </select>
              </label>
              <button className="button button--primary" disabled={busy}>
                Emitir versión
              </button>
            </form>
          ) : null}
          {instrument.versions.map((version) => (
            <div className="document-version" key={version.id}>
              <div>
                <strong>Emisión v{version.version}</strong>
                <StatusBadge value={version.state} />
                <p>
                  <code>snapshot {version.snapshot_sha256}</code>
                </p>
                {version.artifact ? (
                  <p>
                    <code>PDF {version.artifact.sha256}</code> ·{" "}
                    {version.artifact.verified_at
                      ? "integridad verificada"
                      : "verificación pendiente"}
                  </p>
                ) : null}
                {version.acceptance ? (
                  <p>Aceptado {new Date(version.acceptance.accepted_at).toLocaleString("es-EC")}</p>
                ) : (
                  <p className="muted">Sin aceptación</p>
                )}
              </div>
              <div className="button-row">
                {version.artifact ? (
                  <a
                    className="button button--ghost"
                    href={`/api/v1/organizations/${organizationId}/documents/artifacts/${version.artifact.id}/download/`}
                  >
                    Descargar
                  </a>
                ) : null}
                {canGrants && version.artifact?.verified_at ? (
                  <button
                    className="button button--secondary"
                    onClick={() => {
                      onMutate(async () => {
                        const expires = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
                        const secret = await api<{ token: string }>(
                          `/api/v1/organizations/${organizationId}/documents/grants/`,
                          {
                            method: "POST",
                            body: JSON.stringify({
                              issued_version_id: version.id,
                              purpose: "accept",
                              expires_at: expires,
                              max_exchanges: 1,
                            }),
                          },
                        );
                        onExternalLink(
                          `${window.location.origin}/documents/access#${encodeURIComponent(secret.token)}`,
                        );
                      });
                    }}
                  >
                    Crear enlace de aceptación
                  </button>
                ) : null}
              </div>
              {version.grants.length ? (
                <ul>
                  {version.grants.map((grant) => (
                    <li key={grant.id}>
                      {grant.purpose} ·{" "}
                      {grant.revoked_at
                        ? "revocado"
                        : `vence ${new Date(grant.expires_at).toLocaleString("es-EC")}`}
                      {canGrants && !grant.revoked_at ? (
                        <button
                          className="link-button"
                          onClick={() => {
                            onMutate(() =>
                              api(
                                `/api/v1/organizations/${organizationId}/documents/grants/${grant.id}/revoke/`,
                                { method: "POST" },
                              ),
                            );
                          }}
                        >
                          Revocar
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
        </article>
      ))}
      {canFiles ? (
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            data.set("record_id", recordId);
            onMutate(() =>
              api(`/api/v1/organizations/${organizationId}/documents/external-files/`, {
                method: "POST",
                body: data,
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Archivo externo PDF/JPEG/PNG
            <input name="file" type="file" accept="application/pdf,image/jpeg,image/png" required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Subir a cuarentena
          </button>
        </form>
      ) : null}
      {record.external_files.map((file) => (
        <div className="document-version" key={file.id}>
          <span>{file.display_name}</span>
          <StatusBadge value={file.state} />
          {file.state === "clean" ? (
            <a
              href={`/api/v1/organizations/${organizationId}/documents/external-files/${file.id}/download/`}
            >
              Descargar
            </a>
          ) : (
            <small>{file.validation_detail || "No disponible hasta resultado clean"}</small>
          )}
        </div>
      ))}
    </div>
  );
}

function RetentionPanel({
  organizationId,
  data,
  canManage,
  busy,
  onMutate,
}: {
  organizationId: string;
  data: RetentionData;
  canManage: boolean;
  busy: boolean;
  onMutate: (operation: () => Promise<unknown>) => void;
}) {
  return (
    <section className="panel form-stack" aria-labelledby="retention-title">
      <div>
        <p className="eyebrow">Sin destrucción física</p>
        <h2 id="retention-title">Retención y legal hold</h2>
        <p className="muted">
          La elegibilidad se registra como evidencia; P9 no incluye borrado, purge ni disposición
          física.
        </p>
      </div>
      {canManage ? (
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            onMutate(() =>
              api(`/api/v1/organizations/${organizationId}/documents/retention/`, {
                method: "POST",
                body: JSON.stringify({
                  key: formText(form, "key"),
                  version: Number(formText(form, "version")),
                  name: formText(form, "name"),
                  classification: formText(form, "classification"),
                  rules: { basis: formText(form, "basis") },
                }),
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Clave
            <input name="key" pattern="[a-z][a-z0-9_]+" required />
          </label>
          <label>
            Versión
            <input name="version" type="number" min="1" defaultValue="1" required />
          </label>
          <label>
            Nombre
            <input name="name" required />
          </label>
          <label>
            Clasificación
            <input name="classification" required />
          </label>
          <label>
            Fundamento aprobado
            <input name="basis" required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Crear política
          </button>
        </form>
      ) : null}
      <div className="document-grid">
        {data.policies.map((policy) => (
          <article className="document-card" key={policy.id}>
            <div className="panel-header">
              <h3>
                {policy.name} v{policy.version}
              </h3>
              <StatusBadge value={policy.status} />
            </div>
            <p>{policy.classification}</p>
            {canManage && policy.status === "draft" ? (
              <button
                className="button button--primary"
                onClick={() => {
                  onMutate(() =>
                    api(
                      `/api/v1/organizations/${organizationId}/documents/retention/policies/${policy.id}/activate/`,
                      { method: "POST" },
                    ),
                  );
                }}
              >
                Activar política
              </button>
            ) : null}
          </article>
        ))}
      </div>
      {canManage && data.policies.some((policy) => policy.status === "active") ? (
        <form
          className="compact-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            onMutate(() =>
              api(`/api/v1/organizations/${organizationId}/documents/retention/assignments/`, {
                method: "POST",
                body: JSON.stringify({
                  policy_id: formText(form, "policy_id"),
                  target_type: formText(form, "target_type"),
                  target_id: formText(form, "target_id"),
                }),
              }),
            );
            event.currentTarget.reset();
          }}
        >
          <label>
            Política activa
            <select name="policy_id">
              {data.policies
                .filter((policy) => policy.status === "active")
                .map((policy) => (
                  <option value={policy.id} key={policy.id}>
                    {policy.name} v{policy.version}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Tipo de evidencia
            <select name="target_type">
              <option value="contractual_record">Expediente</option>
              <option value="issued_version">Versión emitida</option>
              <option value="generated_artifact">Artefacto generado</option>
              <option value="external_file">Archivo externo</option>
            </select>
          </label>
          <label>
            UUID objetivo
            <input name="target_id" required />
          </label>
          <button className="button button--secondary" disabled={busy}>
            Asignar política
          </button>
        </form>
      ) : null}
      {data.assignments.map((assignment) => {
        const hold = data.holds.find(
          (item) => item.assignment_id === assignment.id && !item.released_at,
        );
        return (
          <div className="document-version" key={assignment.id}>
            <div>
              <strong>{assignment.target_type}</strong>
              <p>
                <code>{assignment.target_id}</code>
              </p>
              <StatusBadge value={assignment.state} />
            </div>
            {canManage && !hold ? (
              <form
                className="compact-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = new FormData(event.currentTarget);
                  const localValue = formText(form, "eligible_at");
                  onMutate(() =>
                    api(
                      `/api/v1/organizations/${organizationId}/documents/retention/assignments/${assignment.id}/eligibility/`,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          eligible_at: new Date(localValue).toISOString(),
                          rationale: formText(form, "rationale"),
                        }),
                      },
                    ),
                  );
                }}
              >
                <label>
                  Elegible desde
                  <input name="eligible_at" type="datetime-local" required />
                </label>
                <label>
                  Fundamento de evaluación
                  <input name="rationale" required />
                </label>
                <button className="button button--ghost" disabled={busy}>
                  Registrar elegibilidad
                </button>
              </form>
            ) : null}
            {canManage ? (
              hold ? (
                <button
                  className="button button--ghost"
                  onClick={() => {
                    onMutate(() =>
                      api(
                        `/api/v1/organizations/${organizationId}/documents/retention/holds/${hold.id}/release/`,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            reason: "Liberación autorizada registrada desde backoffice",
                          }),
                        },
                      ),
                    );
                  }}
                >
                  Liberar hold
                </button>
              ) : (
                <button
                  className="button button--ghost"
                  onClick={() => {
                    onMutate(() =>
                      api(`/api/v1/organizations/${organizationId}/documents/retention/holds/`, {
                        method: "POST",
                        body: JSON.stringify({
                          assignment_id: assignment.id,
                          reason: "Hold autorizado registrado desde backoffice",
                        }),
                      }),
                    );
                  }}
                >
                  Aplicar legal hold
                </button>
              )
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
