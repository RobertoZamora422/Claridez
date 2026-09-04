import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { api, ApiError } from "../../api";
import type { Catalog } from "./types";
import { useAnalyticsCatalog } from "./useAnalyticsCatalog";

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: vi.fn(),
}));
const catalog: Catalog = {
  catalog_version: "p15-v1",
  catalog_hash: "a".repeat(64),
  profile: "commercial",
  capabilities: ["analytics:read_dashboard"],
  metrics: [],
  preset: [],
  timezone: "America/Guayaquil",
  currency: "USD",
  server_now: "2026-09-04T12:00:00Z",
  periods: [],
};
beforeEach(() => {
  vi.mocked(api).mockReset();
});
afterEach(cleanup);

it("exposes a recoverable network error and retries without keeping stale data", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("Sin conexión")).mockResolvedValueOnce(catalog);
  const { result } = renderHook(() => useAnalyticsCatalog("a"));
  expect(result.current.state.status).toBe("loading");
  await waitFor(() => {
    expect(result.current.state).toEqual({ status: "error", message: "Sin conexión" });
  });
  act(() => {
    result.current.retry();
  });
  expect(result.current.state.status).toBe("loading");
  await waitFor(() => {
    expect(result.current.state).toEqual({ status: "ready", catalog });
  });
  expect(api).toHaveBeenCalledTimes(2);
});

it.each([401, 403, 404])("does not treat denial %s as a cached grant", async (status) => {
  vi.mocked(api).mockRejectedValue(new ApiError("denied", "Sin acceso", status));
  const { result } = renderHook(() => useAnalyticsCatalog("a"));
  await waitFor(() => {
    expect(result.current.state).toEqual({ status: "denied" });
  });
});

it("hides the previous organization's catalog immediately during a switch", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce(catalog)
    .mockReturnValueOnce(
      new Promise(() => {
        // Intentionally pending while the second tenant is loading.
      }),
    );
  const { result, rerender } = renderHook(({ oid }) => useAnalyticsCatalog(oid), {
    initialProps: { oid: "a" },
  });
  await waitFor(() => {
    expect(result.current.state.status).toBe("ready");
  });
  rerender({ oid: "b" });
  expect(result.current.state).toEqual({ status: "loading" });
  expect(api).toHaveBeenLastCalledWith("/api/v1/organizations/b/analytics/catalog/");
});

it("ignores a late response from the previous organization", async () => {
  let finishFirst: ((value: Catalog) => void) | undefined;
  vi.mocked(api)
    .mockReturnValueOnce(
      new Promise<Catalog>((resolve) => {
        finishFirst = resolve;
      }),
    )
    .mockResolvedValueOnce({ ...catalog, profile: "operations" });
  const { result, rerender } = renderHook(({ oid }) => useAnalyticsCatalog(oid), {
    initialProps: { oid: "a" },
  });
  rerender({ oid: "b" });
  await waitFor(() => {
    expect(result.current.state.status).toBe("ready");
  });
  await act(async () => {
    finishFirst?.(catalog);
    await Promise.resolve();
  });
  expect(result.current.state).toEqual({
    status: "ready",
    catalog: { ...catalog, profile: "operations" },
  });
});
