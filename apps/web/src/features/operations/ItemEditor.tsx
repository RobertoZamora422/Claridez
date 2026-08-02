import { useState } from "react";

import { api, type PreparationItem } from "../../api";
import { message } from "../../shared/utilities";
import { ITEM_STATUS_LABELS } from "./constants";

export function ItemEditor({
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
