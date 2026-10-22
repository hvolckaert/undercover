import { useCallback, useEffect, useState } from "react";
import { getJson } from "./api";

export interface Resource<T> {
  data: T | undefined;
  error: string | undefined;
  reload: () => void;
}

export function useResource<T>(
  path: string,
  everyMs: number | null = null,
): Resource<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    getJson<T>(path).then(
      (result) => {
        if (live) {
          setData(result);
          setError(undefined);
        }
      },
      (reason: unknown) => {
        if (live) setError(String(reason));
      },
    );
    return () => {
      live = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (everyMs === null) return;
    const timer = setInterval(() => {
      setTick((t) => t + 1);
    }, everyMs);
    return () => {
      clearInterval(timer);
    };
  }, [everyMs]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  return { data, error, reload };
}
