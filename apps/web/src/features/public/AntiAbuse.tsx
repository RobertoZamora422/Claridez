import { useEffect, useRef, useState } from "react";

import { p14ExternalApi } from "../../api";

declare global {
  interface Window {
    turnstile?: {
      render: (
        element: HTMLElement,
        options: {
          sitekey: string;
          action: string;
          callback: (token: string) => void;
          "expired-callback": () => void;
          "error-callback": () => void;
        },
      ) => string;
      remove: (widgetId: string) => void;
    };
  }
}

interface SecurityConfig {
  antiabuse_provider: "deterministic" | "turnstile";
  turnstile_site_key: string;
}

export function AntiAbuse({
  action,
  resetKey,
  onToken,
}: {
  action: string;
  resetKey: number;
  onToken: (token: string) => void;
}) {
  const host = window.location.hostname;
  const container = useRef<HTMLDivElement>(null);
  const tokenCallback = useRef(onToken);
  const [config, setConfig] = useState<SecurityConfig | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    tokenCallback.current = onToken;
  }, [onToken]);

  useEffect(() => {
    void p14ExternalApi<SecurityConfig>("/api/v1/public/security-config/")
      .then(setConfig)
      .catch(() => {
        setError("No fue posible iniciar la protección antiabuso.");
      });
  }, []);

  useEffect(() => {
    if (!config) return;
    if (config.antiabuse_provider === "deterministic") {
      tokenCallback.current(`test-pass:${crypto.randomUUID()}`);
      return;
    }
    if (!config.turnstile_site_key || !container.current) {
      setError("La protección antiabuso no está configurada.");
      return;
    }
    let cancelled = false;
    let widgetId = "";
    const render = () => {
      if (cancelled || !container.current || !window.turnstile) return;
      widgetId = window.turnstile.render(container.current, {
        sitekey: config.turnstile_site_key,
        action,
        callback: (token) => {
          tokenCallback.current(token);
        },
        "expired-callback": () => {
          tokenCallback.current("");
        },
        "error-callback": () => {
          setError("No fue posible validar la protección antiabuso.");
        },
      });
    };
    const existing = document.querySelector<HTMLScriptElement>("script[data-claridez-turnstile]");
    if (window.turnstile) render();
    else if (existing) existing.addEventListener("load", render, { once: true });
    else {
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.dataset.claridezTurnstile = "true";
      script.addEventListener("load", render, { once: true });
      document.head.append(script);
    }
    return () => {
      cancelled = true;
      if (widgetId && window.turnstile) window.turnstile.remove(widgetId);
    };
  }, [action, config, resetKey]);

  return (
    <div className="antiabuse" data-hostname={host}>
      <div ref={container} />
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}
