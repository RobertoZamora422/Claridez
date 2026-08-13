import { useEffect, useState } from "react";

import { externalApi } from "../../api";
import { BrandLogo } from "../../Brand";
import { Loading, Notice, StatusBadge } from "../../shared/components";
import { formText, message } from "../../shared/utilities";

interface ExternalDocument {
  title: string;
  issued_version_id: string;
  instrument_type: string;
  version: number;
  issued_at: string | null;
  artifact: { id: string; sha256: string; size_bytes: number; media_type: string };
  permissions: { read: boolean; download: boolean; accept: boolean };
  manifestation: { text: string; version: string } | null;
}

export function ExternalDocumentView({ token }: { token: string | null }) {
  const [document, setDocument] = useState<ExternalDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        if (token) {
          await externalApi("/api/v1/external/documents/exchange/", {
            method: "POST",
            body: JSON.stringify({ token }),
          });
          window.history.replaceState({}, "", "/documents/external");
        }
        setDocument(await externalApi("/api/v1/external/documents/session/"));
      } catch (caught) {
        setError(message(caught));
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [token]);

  async function acceptDocument(form: HTMLFormElement) {
    if (!document?.manifestation) return;
    setBusy(true);
    setError("");
    try {
      const challenge = await externalApi<{ challenge_token: string }>(
        "/api/v1/external/documents/challenge/",
        { method: "POST" },
      );
      const data = new FormData(form);
      await externalApi("/api/v1/external/documents/accept/", {
        method: "POST",
        body: JSON.stringify({
          challenge_token: challenge.challenge_token,
          manifestation_version: document.manifestation.version,
          affirmative: data.get("affirmative") === "on",
          asserted_name: formText(data, "asserted_name"),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Guayaquil",
        }),
      });
      setAccepted(true);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  if (loading)
    return (
      <main className="external-document-shell">
        <Loading label="Abriendo documento seguro…" />
      </main>
    );
  if (!document)
    return (
      <main className="external-document-shell">
        <BrandLogo />
        <section className="external-document-card">
          <h1>Enlace no disponible</h1>
          <Notice>{error || "El enlace es inválido, expiró o fue revocado."}</Notice>
          <p className="muted">
            Solicita un nuevo enlace a la organización que emitió el documento.
          </p>
        </section>
      </main>
    );
  return (
    <main className="external-document-shell">
      <header className="external-document-brand">
        <BrandLogo />
        <span>Acceso documental privado</span>
      </header>
      <section className="external-document-card" aria-labelledby="external-document-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Documento emitido</p>
            <h1 id="external-document-title">{document.title}</h1>
          </div>
          <StatusBadge value={accepted ? "accepted" : "issued"} />
        </div>
        <dl className="document-facts">
          <div>
            <dt>Versión</dt>
            <dd>{document.version}</dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>
              <code>{document.artifact.sha256}</code>
            </dd>
          </div>
          <div>
            <dt>Tamaño</dt>
            <dd>{Math.ceil(document.artifact.size_bytes / 1024)} KB</dd>
          </div>
        </dl>
        {error && <Notice>{error}</Notice>}
        <iframe
          className="document-pdf-frame"
          title={`Documento: ${document.title}`}
          src="/api/v1/external/documents/artifact/"
        />
        {document.permissions.download ? (
          <a
            className="button button--secondary"
            href="/api/v1/external/documents/artifact/"
            download
          >
            Descargar PDF exacto
          </a>
        ) : null}
        {accepted ? (
          <Notice tone="info">Tu aceptación quedó registrada para este artefacto exacto.</Notice>
        ) : document.permissions.accept && document.manifestation ? (
          <form
            className="acceptance-panel form-stack"
            onSubmit={(event) => {
              event.preventDefault();
              void acceptDocument(event.currentTarget);
            }}
          >
            <h2>Aceptación electrónica</h2>
            <p>{document.manifestation.text}</p>
            <label>
              Nombre de quien acepta
              <input name="asserted_name" autoComplete="name" minLength={2} required />
            </label>
            <label className="check-row">
              <input name="affirmative" type="checkbox" required />
              Manifiesto afirmativamente mi aceptación del documento mostrado.
            </label>
            <p className="muted">
              Este es un mecanismo propio de evidencia contractual de Claridez; no se presenta como
              firma electrónica acreditada.
            </p>
            <button className="button button--primary" disabled={busy}>
              {busy ? "Registrando…" : "Aceptar este documento"}
            </button>
          </form>
        ) : null}
      </section>
    </main>
  );
}
