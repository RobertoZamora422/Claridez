import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { api, type EventTypeDefinition, type Space, type Venue } from "../../api";
import { Loading, Notice } from "../../shared/components";
import { message } from "../../shared/utilities";

interface Membership {
  id: string;
  role: string;
  status: string;
  user: { display_name: string; email: string };
}
interface FormVersion {
  id: string;
  version: number;
  status: string;
  title: string;
  introduction: string;
  field_schema: Record<string, unknown>;
  event_type_options: { id: string; revision: number }[];
  location_options: { space_id: string; space_revision: number; venue_revision: number }[];
  duration_options_minutes: number[];
  timezone_name: string;
  responsible_membership_id: string;
  origin: string;
  origin_detail: string;
  attribution: Record<string, unknown>;
  consent_presentation: {
    purpose: string;
    channel: string;
    text: string;
    version: string;
    required: boolean;
  }[];
  portal_scopes: string[];
  acknowledgement_template_version_id: string | null;
  configuration_sha256: string;
}
interface PublicForm {
  id: string;
  name: string;
  status: string;
  versions: FormVersion[];
}
interface TemplateVersion {
  id: string;
  version: number;
  status: string;
  subject_template: string;
  body_template: string;
  variable_names: string[];
  content_sha256: string;
}
interface Template {
  id: string;
  name: string;
  channel: string;
  purpose: string;
  is_active: boolean;
  versions: TemplateVersion[];
}
interface Delivery {
  id: string;
  message_id: string | null;
  purpose: string;
  channel: string;
  status: string;
  outbox_state: string;
  recipient_fingerprint: string;
  provider: string;
  attempt_count: number;
  max_attempts: number;
  last_error_category: string;
  created_at: string;
}
interface Grant {
  id: string;
  event_request_reference: string;
  scopes: string[];
  state: string;
  revision: number;
}
interface Preference {
  person_reference: string;
  channel: string;
  purpose: string;
  destination_fingerprint: string;
  effective_suppression: string;
  last_action: string;
  occurred_at: string;
}

const closedScopes = [
  "event:read",
  "quotation:read",
  "schedule:read",
  "documents:read",
  "documents:download",
  "documents:accept",
  "receivables:read",
  "preferences:manage",
];

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

export function P14WorkspaceView({
  organizationId,
  capabilities,
  timezone,
}: {
  organizationId: string;
  capabilities: Set<string>;
  timezone: string;
}) {
  const [forms, setForms] = useState<PublicForm[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [eventTypes, setEventTypes] = useState<EventTypeDefinition[]>([]);
  const [venues, setVenues] = useState<Venue[]>([]);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [formDraft, setFormDraft] = useState({
    name: "Captación principal",
    title: "Cuéntanos sobre tu evento",
    introduction: "El equipo comercial revisará la solicitud.",
    duration: "120",
    responsible: "",
    consentText: "Acepto recibir actualizaciones de servicio sobre esta solicitud.",
  });
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [selectedSpaces, setSelectedSpaces] = useState<string[]>([]);
  const [formVersionSource, setFormVersionSource] = useState<FormVersion | null>(null);
  const [editingFormId, setEditingFormId] = useState("");
  const [templateDraft, setTemplateDraft] = useState({
    name: "",
    channel: "email",
    purpose: "service_update",
    subject: "",
    body: "",
    variables: "",
  });
  const [editingTemplateId, setEditingTemplateId] = useState("");
  const [preferenceDraft, setPreferenceDraft] = useState({
    person: "",
    channel: "email",
    purpose: "service_update",
    action: "suppress",
    reason: "",
  });
  const [grantDraft, setGrantDraft] = useState({
    eventRequest: "",
    scopes: ["event:read", "quotation:read", "preferences:manage"],
  });

  const load = useCallback(async () => {
    try {
      const requests: Promise<unknown>[] = [
        capabilities.has("public_form:read")
          ? api<{ forms: PublicForm[] }>(
              `/api/v1/organizations/${organizationId}/public-forms/`,
            ).then((body) => {
              setForms(body.forms);
            })
          : Promise.resolve(),
        capabilities.has("communication_template:read")
          ? api<{ templates: Template[] }>(
              `/api/v1/organizations/${organizationId}/communications/templates/`,
            ).then((body) => {
              setTemplates(body.templates);
            })
          : Promise.resolve(),
        capabilities.has("communication_delivery:read")
          ? api<{ deliveries: Delivery[] }>(
              `/api/v1/organizations/${organizationId}/communications/deliveries/`,
            ).then((body) => {
              setDeliveries(body.deliveries);
            })
          : Promise.resolve(),
        capabilities.has("portal_grant:read")
          ? api<{ grants: Grant[] }>(`/api/v1/organizations/${organizationId}/portal-grants/`).then(
              (body) => {
                setGrants(body.grants);
              },
            )
          : Promise.resolve(),
        capabilities.has("communication_preference:read")
          ? api<{ preferences: Preference[] }>(
              `/api/v1/organizations/${organizationId}/communications/preferences/`,
            ).then((body) => {
              setPreferences(body.preferences);
            })
          : Promise.resolve(),
      ];
      if (capabilities.has("public_form:manage")) {
        requests.push(
          api<{ event_types: EventTypeDefinition[] }>(
            `/api/v1/organizations/${organizationId}/event-types/`,
          ).then((body) => {
            const active = body.event_types.filter((item) => item.is_active);
            setEventTypes(active);
            setSelectedEventTypes((current) =>
              current.length ? current : active.map((item) => item.id),
            );
          }),
          api<{ venues: Venue[] }>(`/api/v1/organizations/${organizationId}/venues/`).then(
            (body) => {
              setVenues(body.venues);
              setSelectedSpaces((current) =>
                current.length
                  ? current
                  : body.venues.flatMap((venue) =>
                      venue.spaces.filter((space) => space.is_active).map((space) => space.id),
                    ),
              );
            },
          ),
          api<{ memberships: Membership[] }>(
            `/api/v1/organizations/${organizationId}/memberships/`,
          ).then((body) => {
            const responsible = body.memberships.filter(
              (item) =>
                item.status === "active" &&
                ["owner", "administrator", "commercial"].includes(item.role),
            );
            setMemberships(responsible);
          }),
        );
      }
      await Promise.all(requests);
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setLoading(false);
    }
  }, [capabilities, organizationId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [load]);

  async function createPublicForm(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    const locations = venues.flatMap((venue) =>
      venue.spaces
        .filter((space) => selectedSpaces.includes(space.id))
        .map((space) => ({
          space_id: space.id,
          space_revision: space.revision,
          venue_revision: venue.revision,
        })),
    );
    try {
      const consentHash = await sha256(formDraft.consentText);
      const sourceConsent = formVersionSource?.consent_presentation[0];
      const versionPayload = {
        title: formDraft.title,
        introduction: formDraft.introduction,
        field_schema: formVersionSource?.field_schema ?? {
          required: [
            "full_name",
            "phone",
            "event_type_id",
            "space_id",
            "starts_at_local",
            "duration_minutes",
            "estimated_guests",
            "general_need",
          ],
          optional: ["email", "notes"],
          labels: {},
        },
        event_type_options: eventTypes
          .filter((item) => selectedEventTypes.includes(item.id))
          .map((item) => ({ id: item.id, revision: item.revision })),
        location_options: locations,
        duration_options_minutes: [Number(formDraft.duration)],
        timezone_name: timezone,
        responsible_membership_id: formDraft.responsible,
        origin: formVersionSource?.origin ?? "website",
        origin_detail: formVersionSource?.origin_detail ?? "Formulario público P14",
        attribution: formVersionSource?.attribution ?? { source: "public_form" },
        consent_presentation: formDraft.consentText
          ? [
              {
                purpose: sourceConsent?.purpose ?? "service_update",
                channel: sourceConsent?.channel ?? "email",
                text: formDraft.consentText,
                text_sha256: consentHash,
                version: `service-${new Date().toISOString()}`,
                required: sourceConsent?.required ?? false,
              },
            ]
          : [],
        portal_scopes: formVersionSource?.portal_scopes ?? closedScopes,
        acknowledgement_template_version_id:
          formVersionSource?.acknowledgement_template_version_id ?? null,
      };
      const endpoint = editingFormId
        ? `/api/v1/organizations/${organizationId}/public-forms/${editingFormId}/versions/`
        : `/api/v1/organizations/${organizationId}/public-forms/`;
      const created = await api<{ locator?: string }>(endpoint, {
        method: "POST",
        body: JSON.stringify(
          editingFormId ? versionPayload : { name: formDraft.name, ...versionPayload },
        ),
      });
      setNotice(
        editingFormId
          ? "Nueva versión creada como borrador; la versión publicada continúa activa."
          : `Borrador creado. Locator estable: ${created.locator ?? "generado"}`,
      );
      setEditingFormId("");
      setFormVersionSource(null);
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  async function createCommunicationTemplate(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const endpoint = editingTemplateId
        ? `/api/v1/organizations/${organizationId}/communications/templates/${editingTemplateId}/versions/`
        : `/api/v1/organizations/${organizationId}/communications/templates/`;
      const versionPayload = {
        subject_template: templateDraft.subject,
        body_template: templateDraft.body,
        variable_names: templateDraft.variables
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      };
      await api(endpoint, {
        method: "POST",
        body: JSON.stringify(
          editingTemplateId
            ? versionPayload
            : {
                name: templateDraft.name,
                channel: templateDraft.channel,
                purpose: templateDraft.purpose,
                ...versionPayload,
              },
        ),
      });
      setNotice(
        editingTemplateId
          ? "Nueva versión de plantilla creada como borrador."
          : "Plantilla creada como borrador.",
      );
      setEditingTemplateId("");
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  function prepareFormVersion(form: PublicForm, version: FormVersion) {
    setEditingFormId(form.id);
    setFormVersionSource(version);
    setFormDraft({
      name: form.name,
      title: version.title,
      introduction: version.introduction,
      duration: String(version.duration_options_minutes[0] ?? 120),
      responsible: version.responsible_membership_id,
      consentText: version.consent_presentation[0]?.text ?? "",
    });
    setSelectedEventTypes(version.event_type_options.map((item) => item.id));
    setSelectedSpaces(version.location_options.map((item) => item.space_id));
  }

  function prepareTemplateVersion(template: Template, version: TemplateVersion) {
    setEditingTemplateId(template.id);
    setTemplateDraft({
      name: template.name,
      channel: template.channel,
      purpose: template.purpose,
      subject: version.subject_template,
      body: version.body_template,
      variables: version.variable_names.join(", "),
    });
  }

  async function rotateFormLocator(form: PublicForm) {
    if (!window.confirm("El enlace público actual dejará de funcionar. ¿Continuar?")) return;
    try {
      const result = await api<{ locator: string }>(
        `/api/v1/organizations/${organizationId}/public-forms/${form.id}/locator/rotate/`,
        { method: "POST" },
      );
      setNotice(`Nuevo locator estable — guárdalo ahora: ${result.locator}`);
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  async function retireForm(form: PublicForm) {
    if (!window.confirm("El formulario y todos sus enlaces quedarán retirados. ¿Continuar?"))
      return;
    try {
      await api(`/api/v1/organizations/${organizationId}/public-forms/${form.id}/retire/`, {
        method: "POST",
      });
      setNotice("El formulario fue retirado sin alterar sus submissions históricos.");
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  async function issuePortalGrant(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      await api(`/api/v1/organizations/${organizationId}/portal-grants/`, {
        method: "POST",
        body: JSON.stringify({
          event_request_id: grantDraft.eventRequest,
          scopes: grantDraft.scopes,
        }),
      });
      setNotice("Grant emitido sin convertir al cliente en miembro del workspace.");
      setGrantDraft((current) => ({ ...current, eventRequest: "" }));
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }

  if (loading) return <Loading label="Cargando formularios, comunicaciones y portal…" />;

  return (
    <section className="p14-workspace">
      <header className="page-header">
        <div>
          <p className="eyebrow">P14</p>
          <h1>Experiencia externa del cliente</h1>
          <p>Formularios estructurados, entrega transaccional y grants de Portal.</p>
        </div>
        <button className="button button--ghost" onClick={() => void load()}>
          Actualizar
        </button>
      </header>
      {notice ? (
        <div className="success-panel" role="status">
          {notice}
        </div>
      ) : null}
      {error ? <Notice>{error}</Notice> : null}

      {capabilities.has("public_form:read") ? (
        <section className="panel">
          <h2>Formularios públicos</h2>
          <div className="p14-grid">
            {forms.map((form) => (
              <article className="portal-item" key={form.id}>
                <strong>{form.name}</strong>
                <span>{form.status}</span>
                <ul>
                  {form.versions.map((version) => (
                    <li key={version.id}>
                      v{version.version} · {version.status}
                      {version.status === "draft" && capabilities.has("public_form:publish") ? (
                        <button
                          className="button button--ghost"
                          onClick={() =>
                            void api(
                              `/api/v1/organizations/${organizationId}/public-forms/versions/${version.id}/publish/`,
                              { method: "POST" },
                            ).then(load)
                          }
                        >
                          Publicar
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {capabilities.has("public_form:manage") &&
                !form.versions.some((version) => version.status === "draft") &&
                form.versions.length ? (
                  <button
                    className="button button--ghost"
                    onClick={() => {
                      const latest = form.versions.at(-1);
                      if (latest) prepareFormVersion(form, latest);
                    }}
                  >
                    Preparar nueva versión
                  </button>
                ) : null}
                {form.status === "active" &&
                form.versions.some((version) => version.status === "published") &&
                capabilities.has("public_form:publish") ? (
                  <div className="button-row">
                    <button
                      className="button button--ghost"
                      onClick={() => void rotateFormLocator(form)}
                    >
                      Rotar enlace público
                    </button>
                    <button className="button button--danger" onClick={() => void retireForm(form)}>
                      Retirar formulario
                    </button>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
          {capabilities.has("public_form:manage") ? (
            <details open={editingFormId ? true : undefined}>
              <summary>
                {editingFormId
                  ? "Editar nueva versión estructurada"
                  : "Crear formulario estructurado"}
              </summary>
              <form className="structured-form" onSubmit={(event) => void createPublicForm(event)}>
                <div className="form-grid">
                  <label>
                    Nombre interno
                    <input
                      required
                      value={formDraft.name}
                      onChange={(event) => {
                        setFormDraft({ ...formDraft, name: event.target.value });
                      }}
                    />
                  </label>
                  <label>
                    Título público
                    <input
                      required
                      value={formDraft.title}
                      onChange={(event) => {
                        setFormDraft({ ...formDraft, title: event.target.value });
                      }}
                    />
                  </label>
                  <label>
                    Duración en minutos
                    <input
                      required
                      min="15"
                      max="1440"
                      type="number"
                      value={formDraft.duration}
                      onChange={(event) => {
                        setFormDraft({ ...formDraft, duration: event.target.value });
                      }}
                    />
                  </label>
                  <label>
                    Responsable
                    <select
                      required
                      value={formDraft.responsible}
                      onChange={(event) => {
                        setFormDraft({ ...formDraft, responsible: event.target.value });
                      }}
                    >
                      <option value="">Selecciona</option>
                      {memberships.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.user.display_name || item.user.email} · {item.role}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Introducción
                  <textarea
                    value={formDraft.introduction}
                    onChange={(event) => {
                      setFormDraft({ ...formDraft, introduction: event.target.value });
                    }}
                  />
                </label>
                <fieldset>
                  <legend>Tipos publicables</legend>
                  {eventTypes.map((item) => (
                    <label className="check-row" key={item.id}>
                      <input
                        type="checkbox"
                        checked={selectedEventTypes.includes(item.id)}
                        onChange={(event) => {
                          setSelectedEventTypes(
                            event.target.checked
                              ? [...selectedEventTypes, item.id]
                              : selectedEventTypes.filter((id) => id !== item.id),
                          );
                        }}
                      />
                      <span>
                        {item.name} · revisión {item.revision}
                      </span>
                    </label>
                  ))}
                </fieldset>
                <fieldset>
                  <legend>Espacios publicables</legend>
                  {venues.flatMap((venue) =>
                    venue.spaces.map((space: Space) => (
                      <label className="check-row" key={space.id}>
                        <input
                          type="checkbox"
                          checked={selectedSpaces.includes(space.id)}
                          onChange={(event) => {
                            setSelectedSpaces(
                              event.target.checked
                                ? [...selectedSpaces, space.id]
                                : selectedSpaces.filter((id) => id !== space.id),
                            );
                          }}
                        />
                        <span>
                          {venue.name} · {space.name} · revisión {space.revision}
                        </span>
                      </label>
                    )),
                  )}
                </fieldset>
                <label>
                  Texto observado de consentimiento
                  <textarea
                    value={formDraft.consentText}
                    onChange={(event) => {
                      setFormDraft({ ...formDraft, consentText: event.target.value });
                    }}
                  />
                </label>
                <button
                  className="button"
                  disabled={
                    !selectedEventTypes.length || !selectedSpaces.length || !formDraft.responsible
                  }
                >
                  {editingFormId ? "Crear nueva versión" : "Crear borrador"}
                </button>
              </form>
            </details>
          ) : null}
        </section>
      ) : null}

      {capabilities.has("communication_template:read") ? (
        <section className="panel">
          <h2>Plantillas de comunicación</h2>
          <div className="p14-grid">
            {templates.map((template) => (
              <article className="portal-item" key={template.id}>
                <strong>{template.name}</strong>
                <span>
                  {template.channel} · {template.purpose}
                </span>
                <ul>
                  {template.versions.map((version) => (
                    <li key={version.id}>
                      v{version.version} · {version.status}
                      {version.status === "draft" &&
                      capabilities.has("communication_template:publish") ? (
                        <button
                          className="button button--ghost"
                          onClick={() =>
                            void api(
                              `/api/v1/organizations/${organizationId}/communications/templates/versions/${version.id}/publish/`,
                              { method: "POST" },
                            ).then(load)
                          }
                        >
                          Publicar
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {capabilities.has("communication_template:manage") &&
                !template.versions.some((version) => version.status === "draft") &&
                template.versions.length ? (
                  <button
                    className="button button--ghost"
                    onClick={() => {
                      const latest = template.versions.at(-1);
                      if (latest) prepareTemplateVersion(template, latest);
                    }}
                  >
                    Preparar nueva versión
                  </button>
                ) : null}
              </article>
            ))}
          </div>
          {capabilities.has("communication_template:manage") ? (
            <details open={editingTemplateId ? true : undefined}>
              <summary>{editingTemplateId ? "Crear nueva versión" : "Crear plantilla"}</summary>
              <form
                className="structured-form"
                onSubmit={(event) => void createCommunicationTemplate(event)}
              >
                <div className="form-grid">
                  <label>
                    Nombre
                    <input
                      required
                      value={templateDraft.name}
                      onChange={(event) => {
                        setTemplateDraft({ ...templateDraft, name: event.target.value });
                      }}
                    />
                  </label>
                  <label>
                    Canal
                    <select
                      value={templateDraft.channel}
                      onChange={(event) => {
                        setTemplateDraft({ ...templateDraft, channel: event.target.value });
                      }}
                    >
                      <option value="email">Correo</option>
                      <option value="whatsapp">WhatsApp</option>
                    </select>
                  </label>
                  <label>
                    Propósito
                    <select
                      value={templateDraft.purpose}
                      onChange={(event) => {
                        setTemplateDraft({ ...templateDraft, purpose: event.target.value });
                      }}
                    >
                      <option value="portal_authentication">Autenticación Portal</option>
                      <option value="capture_acknowledgement">Acuse de captación</option>
                      <option value="service_update">Actualización de servicio</option>
                      <option value="event_reminder">Recordatorio de evento</option>
                      <option value="payment_reminder">Recordatorio de cobro</option>
                      <option value="document_reminder">Recordatorio documental</option>
                      <option value="client_action">Acción del cliente</option>
                    </select>
                  </label>
                  <label>
                    Variables separadas por coma
                    <input
                      value={templateDraft.variables}
                      onChange={(event) => {
                        setTemplateDraft({ ...templateDraft, variables: event.target.value });
                      }}
                    />
                  </label>
                </div>
                <label>
                  Asunto
                  <input
                    value={templateDraft.subject}
                    onChange={(event) => {
                      setTemplateDraft({ ...templateDraft, subject: event.target.value });
                    }}
                  />
                </label>
                <label>
                  Cuerpo
                  <textarea
                    required
                    rows={5}
                    value={templateDraft.body}
                    onChange={(event) => {
                      setTemplateDraft({ ...templateDraft, body: event.target.value });
                    }}
                  />
                </label>
                <button className="button">
                  {editingTemplateId ? "Crear nueva versión" : "Crear borrador"}
                </button>
              </form>
            </details>
          ) : null}
        </section>
      ) : null}

      {capabilities.has("communication_delivery:read") ? (
        <section className="panel">
          <h2>Entregas y fallos</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Propósito</th>
                  <th>Canal</th>
                  <th>Estado</th>
                  <th>Intentos</th>
                  <th>Proveedor</th>
                  <th>Destino minimizado</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.map((delivery) => (
                  <tr key={delivery.id}>
                    <td>{delivery.purpose}</td>
                    <td>{delivery.channel}</td>
                    <td>{delivery.status}</td>
                    <td>
                      {delivery.attempt_count}/{delivery.max_attempts}
                      {delivery.last_error_category ? ` · ${delivery.last_error_category}` : ""}
                    </td>
                    <td>{delivery.provider || "—"}</td>
                    <td>
                      {delivery.recipient_fingerprint ? (
                        <code>{delivery.recipient_fingerprint.slice(0, 12)}…</code>
                      ) : (
                        "Pendiente de resolver"
                      )}
                    </td>
                    <td>
                      {capabilities.has("communication_delivery:retry") &&
                      delivery.message_id &&
                      ["failed", "bounced"].includes(delivery.status) ? (
                        <button
                          className="button button--ghost"
                          onClick={() =>
                            void api(
                              `/api/v1/organizations/${organizationId}/communications/deliveries/${delivery.id}/retry/`,
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  reason: "Reintento manual desde workspace",
                                }),
                              },
                            ).then(load)
                          }
                        >
                          Reintentar
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {capabilities.has("communication_preference:read") ? (
        <section className="panel">
          <h2>Supresión administrativa</h2>
          <p>
            Una restauración interna nunca elimina una baja del cliente ni un hard bounce protegido.
          </p>
          {preferences.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Persona</th>
                    <th>Canal / propósito</th>
                    <th>Estado efectivo</th>
                    <th>Última acción</th>
                  </tr>
                </thead>
                <tbody>
                  {preferences.map((preference) => (
                    <tr
                      key={`${preference.person_reference}:${preference.channel}:${preference.purpose}:${preference.destination_fingerprint}`}
                    >
                      <td>
                        <code>{preference.person_reference}</code>
                      </td>
                      <td>
                        {preference.channel} · {preference.purpose}
                      </td>
                      <td>{preference.effective_suppression || "permitido por preferencia"}</td>
                      <td>{preference.last_action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No hay preferencias o supresiones registradas.</p>
          )}
          <form
            className="structured-form form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              void api(`/api/v1/organizations/${organizationId}/communications/preferences/`, {
                method: "POST",
                body: JSON.stringify({
                  person_id: preferenceDraft.person,
                  channel: preferenceDraft.channel,
                  purpose: preferenceDraft.purpose,
                  action: preferenceDraft.action,
                  reason: preferenceDraft.reason,
                }),
              })
                .then(() => {
                  setNotice("Acción de preferencia registrada en historia append-only.");
                  void load();
                })
                .catch((caught: unknown) => {
                  setError(message(caught));
                });
            }}
          >
            <label>
              Persona canónica
              <input
                required
                value={preferenceDraft.person}
                onChange={(event) => {
                  setPreferenceDraft({ ...preferenceDraft, person: event.target.value });
                }}
              />
            </label>
            <label>
              Canal
              <select
                value={preferenceDraft.channel}
                onChange={(event) => {
                  setPreferenceDraft({ ...preferenceDraft, channel: event.target.value });
                }}
              >
                <option value="email">Correo</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </label>
            <label>
              Propósito
              <input
                required
                value={preferenceDraft.purpose}
                onChange={(event) => {
                  setPreferenceDraft({ ...preferenceDraft, purpose: event.target.value });
                }}
              />
            </label>
            <label>
              Acción
              <select
                value={preferenceDraft.action}
                onChange={(event) => {
                  setPreferenceDraft({ ...preferenceDraft, action: event.target.value });
                }}
              >
                <option value="suppress">Suprimir</option>
                {capabilities.has("communication_preference:restore") ? (
                  <option value="restore">Liberar supresión administrativa</option>
                ) : null}
              </select>
            </label>
            <label>
              Razón
              <input
                required
                value={preferenceDraft.reason}
                onChange={(event) => {
                  setPreferenceDraft({ ...preferenceDraft, reason: event.target.value });
                }}
              />
            </label>
            <button className="button">Registrar acción</button>
          </form>
        </section>
      ) : null}

      {capabilities.has("portal_grant:read") ? (
        <section className="panel">
          <h2>Grants de Portal</h2>
          {capabilities.has("portal_grant:issue") ? (
            <form className="structured-form" onSubmit={(event) => void issuePortalGrant(event)}>
              <label>
                ID de la solicitud comercial
                <input
                  required
                  value={grantDraft.eventRequest}
                  onChange={(event) => {
                    setGrantDraft({ ...grantDraft, eventRequest: event.target.value });
                  }}
                />
              </label>
              <fieldset>
                <legend>Alcances externos explícitos</legend>
                <div className="form-grid">
                  {closedScopes.map((scope) => (
                    <label className="check-row" key={scope}>
                      <input
                        type="checkbox"
                        checked={grantDraft.scopes.includes(scope)}
                        onChange={(event) => {
                          setGrantDraft({
                            ...grantDraft,
                            scopes: event.target.checked
                              ? [...grantDraft.scopes, scope]
                              : grantDraft.scopes.filter((item) => item !== scope),
                          });
                        }}
                      />
                      <span>{scope}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <button className="button" disabled={!grantDraft.scopes.length}>
                Emitir grant
              </button>
            </form>
          ) : null}
          <div className="p14-grid">
            {grants.map((grant) => (
              <article className="portal-item" key={grant.id}>
                <strong>Solicitud {grant.event_request_reference}</strong>
                <span>
                  {grant.state} · revisión {grant.revision}
                </span>
                <small>{grant.scopes.join(", ")}</small>
                {grant.state === "active" && capabilities.has("portal_grant:revoke") ? (
                  <button
                    className="button button--danger"
                    onClick={() =>
                      void api(
                        `/api/v1/organizations/${organizationId}/portal-grants/${grant.id}/revoke/`,
                        { method: "POST", body: JSON.stringify({ revision: grant.revision }) },
                      ).then(load)
                    }
                  >
                    Revocar
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
