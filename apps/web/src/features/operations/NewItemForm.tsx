import { useState, type SyntheticEvent } from "react";

import { api, type OperationEvent, type PreparationItem } from "../../api";
import { message } from "../../shared/utilities";
import { SECTION_LABELS } from "./constants";

export function NewItemForm({
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
