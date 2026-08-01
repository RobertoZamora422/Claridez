import { useState } from "react";

import type { Organization } from "../../api";
import { BrandLogo } from "../../Brand";
import { Notice } from "../../shared/components";
import { message } from "../../shared/utilities";

export function OrganizationPicker({
  organizations,
  onSelect,
}: {
  organizations: Organization[];
  onSelect: (organization: Organization) => Promise<void>;
}) {
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  return (
    <main className="center-layout">
      <section className="picker-card" aria-labelledby="organization-title">
        <BrandLogo />
        <h1 id="organization-title">Elige una organización</h1>
        <p className="muted">El contexto seleccionado define los datos que puedes consultar.</p>
        {error && <Notice>{error}</Notice>}
        {organizations.length === 0 ? (
          <Notice tone="info">Tu cuenta no tiene organizaciones activas.</Notice>
        ) : (
          <div className="organization-list">
            {organizations.map((organization) => (
              <button
                key={organization.id}
                className="organization-option"
                disabled={busyId !== ""}
                onClick={() => {
                  setBusyId(organization.id);
                  setError("");
                  void onSelect(organization).catch((caught: unknown) => {
                    setError(message(caught));
                    setBusyId("");
                  });
                }}
              >
                <span className="organization-avatar" aria-hidden="true">
                  {organization.name.slice(0, 1).toUpperCase()}
                </span>
                <span>
                  <strong>{organization.name}</strong>
                  <small>
                    {busyId === organization.id ? "Abriendo…" : "Abrir centro de control"}
                  </small>
                </span>
                <span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
