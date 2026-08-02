import { useState } from "react";

import { api, type OperationEvent } from "../../api";
import { message } from "../../shared/utilities";

export function PreparationNotes({
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
