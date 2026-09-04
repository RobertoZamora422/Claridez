import { useEffect, useState } from "react";

import { api, ApiError } from "../../api";
import { message } from "../../shared/utilities";
import type { Catalog } from "./types";

type CatalogState =
  | { status: "loading" }
  | { status: "ready"; catalog: Catalog }
  | { status: "denied" }
  | { status: "error"; message: string };

export function useAnalyticsCatalog(organizationId: string) {
  const [attempt, setAttempt] = useState(0);
  const [response, setResponse] = useState<{
    organizationId: string;
    attempt: number;
    state: CatalogState;
  } | null>(null);
  useEffect(() => {
    let active = true;
    const accept = (state: CatalogState) => {
      if (active) setResponse({ organizationId, attempt, state });
    };
    void api<Catalog>(`/api/v1/organizations/${organizationId}/analytics/catalog/`)
      .then((catalog) => {
        accept({ status: "ready", catalog });
      })
      .catch((caught: unknown) => {
        accept(
          caught instanceof ApiError && [401, 403, 404].includes(caught.status)
            ? { status: "denied" }
            : { status: "error", message: message(caught) },
        );
      });
    return () => {
      active = false;
    };
  }, [organizationId, attempt]);
  // Never expose a previous tenant's catalog, even during the render before effect cleanup.
  const state: CatalogState =
    response?.organizationId === organizationId && response.attempt === attempt
      ? response.state
      : { status: "loading" };
  return {
    state,
    retry: () => {
      setAttempt((value) => value + 1);
    },
  };
}
