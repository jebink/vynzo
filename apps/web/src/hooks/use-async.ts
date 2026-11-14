"use client";

import { useEffect, useEffectEvent, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: unknown;
}

/**
 * Runs `load` whenever `key` changes (pass `null` to skip) and aborts the previous request.
 * `key` must change whenever the inputs of `load` change; results for a stale key are ignored.
 */
export function useAsync<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): AsyncState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const run = useEffectEvent(load);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    run(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ key, data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ key, error: error ?? new Error("Request failed") });
      },
    );
    return () => controller.abort();
  }, [key]);

  const current = settled !== null && settled.key === key ? settled : null;
  return {
    data: current?.data,
    error: current?.error,
    loading: key !== null && current === null,
  };
}
