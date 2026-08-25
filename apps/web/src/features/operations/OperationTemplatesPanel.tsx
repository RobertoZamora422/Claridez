import { useCallback, useState } from "react";

import { api, type OperationalTemplateVersion } from "../../api";
import { Notice, StatusBadge } from "../../shared/components";
import { useInitialLoad } from "../../shared/useInitialLoad";
import { message } from "../../shared/utilities";

const EMPTY_DEFINITIONS = `{
  "readiness": [],
  "verifications": [],
  "roles": [],
  "resource_needs": []
}`;

export function OperationTemplatesPanel({
  organizationId,
  canManage,
}: {
  organizationId: string;
  canManage: boolean;
}) {
  const base = `/api/v1/organizations/${organizationId}/operations/templates`;
  const [versions, setVersions] = useState<OperationalTemplateVersion[]>([]);
  const [eventTypeId, setEventTypeId] = useState("");
  const [name, setName] = useState("");
  const [definitions, setDefinitions] = useState(EMPTY_DEFINITIONS);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setVersions(await api<OperationalTemplateVersion[]>(`${base}/`));
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }, [base]);

  useInitialLoad(load);

  async function command(path: string, success: string) {
    setBusy(true);
    setError("");
    try {
      await api(path, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
      });
      setNotice(success);
      await load();
    } catch (caught: unknown) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="operation-panel operation-templates">
      <summary>Plantillas operativas versionadas</summary>
      <p>
        Las publicaciones solo gobiernan eventos futuros. Sin una publicación aplicable se usa
        operations-p13-system-v1.
      </p>
      {notice ? <p className="success-message">{notice}</p> : null}
      {error ? <Notice>{error}</Notice> : null}
      <ul className="operation-compact-list">
        {versions.map((version) => (
          <li key={version.id}>
            <span>
              <strong>{version.name}</strong> · v{version.version} · {version.event_type_id}
            </span>
            <StatusBadge value={version.status} />
            {canManage && version.status === "draft" ? (
              <button
                disabled={busy}
                onClick={() => void command(`${base}/${version.id}/publish/`, "Versión publicada.")}
              >
                Publicar
              </button>
            ) : null}
            {canManage && version.status === "published" ? (
              <button
                disabled={busy}
                onClick={() => void command(`${base}/${version.id}/retire/`, "Versión retirada.")}
              >
                Retirar
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {canManage ? (
        <form
          className="operation-grid-form"
          onSubmit={(event) => {
            event.preventDefault();
            let parsed: Record<string, unknown>;
            try {
              parsed = JSON.parse(definitions) as Record<string, unknown>;
            } catch {
              setError("Las definiciones deben ser JSON válido.");
              return;
            }
            setBusy(true);
            void api(`${base}/`, {
              method: "POST",
              body: JSON.stringify({
                event_type_id: eventTypeId,
                name,
                definitions: parsed,
                idempotency_key: crypto.randomUUID(),
              }),
            })
              .then(async () => {
                setNotice("Borrador versionado creado.");
                await load();
              })
              .catch((caught: unknown) => {
                setError(message(caught));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          <h3>Nueva versión</h3>
          <label>
            Tipo de evento
            <input
              required
              value={eventTypeId}
              onChange={(event) => {
                setEventTypeId(event.target.value);
              }}
              placeholder="UUID del tipo de evento"
            />
          </label>
          <label>
            Nombre estable
            <input
              required
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>
          <label className="operation-grid-form__wide">
            Definiciones tipadas JSON
            <textarea
              required
              rows={12}
              value={definitions}
              onChange={(event) => {
                setDefinitions(event.target.value);
              }}
            />
          </label>
          <button className="button" disabled={busy}>
            Crear borrador
          </button>
        </form>
      ) : null}
    </details>
  );
}
