import { useEffect } from "react";

export function useInitialLoad(load: () => Promise<void>): void {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [load]);
}
