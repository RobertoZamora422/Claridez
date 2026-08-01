import { useState, type SyntheticEvent } from "react";

import { api, login, type User } from "../../api";
import { BrandLogo, BrandSymbol } from "../../Brand";
import { Notice } from "../../shared/components";
import { message } from "../../shared/utilities";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [resetMode, setResetMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    try {
      if (resetMode) {
        await api("/api/v1/auth/password/reset/request/", {
          method: "POST",
          body: JSON.stringify({ email }),
        });
        setInfo("Si la cuenta está disponible, recibirás las instrucciones de recuperación.");
      } else {
        onAuthenticated(await login(email, password));
      }
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-brand" aria-labelledby="brand-title">
        <BrandSymbol />
        <p className="eyebrow">Centro de control para salones de eventos</p>
        <h1 id="brand-title">Todo tu negocio, claro y bajo control.</h1>
        <p>
          Convierte consultas en reservas confirmadas con una agenda confiable y un historial
          comercial preciso.
        </p>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <BrandLogo />
        <h2 id="auth-title">{resetMode ? "Recupera tu acceso" : "Ingresa a tu organización"}</h2>
        <p className="muted">
          {resetMode
            ? "Te enviaremos un enlace si la cuenta existe."
            : "Usa tu cuenta de trabajo para continuar."}
        </p>
        {error && <Notice>{error}</Notice>}
        {info && <Notice tone="info">{info}</Notice>}
        <form onSubmit={(event) => void submit(event)} className="form-stack">
          <label>
            Correo electrónico
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </label>
          {!resetMode && (
            <label>
              Contraseña
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
            </label>
          )}
          <button className="button button--primary" disabled={busy}>
            {busy ? "Procesando…" : resetMode ? "Solicitar recuperación" : "Ingresar"}
          </button>
        </form>
        <button
          className="button button--ghost"
          onClick={() => {
            setResetMode((value) => !value);
            setError("");
            setInfo("");
          }}
        >
          {resetMode ? "Volver al ingreso" : "Olvidé mi contraseña"}
        </button>
      </section>
    </main>
  );
}
