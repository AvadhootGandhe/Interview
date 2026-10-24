"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  retry: () => void;
}

/** Load something once (and again when `key` changes), with a retry. */
export function useLoad<T>(load: () => Promise<T>, key: string, enabled = true): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: unknown; loading: boolean }>({
    data: null,
    error: null,
    loading: enabled,
  });
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    loadRef.current().then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (error) => alive && setState({ data: null, error: error ?? new Error("failed"), loading: false }),
    );
    return () => {
      alive = false;
    };
  }, [key, attempt, enabled]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
