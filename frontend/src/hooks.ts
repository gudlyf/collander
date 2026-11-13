import { useCallback, useEffect, useRef, useState } from "react";
import { api, type QueueItem, type TagInfo } from "./api";

/** Fetch JSON from the API with loading/error state and a reload function. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (path === null) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (mine === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, setData, error, loading, reload: load };
}

export function useTags() {
  return useApi<TagInfo[]>("/tags");
}

/** Poll the import queue; polls quickly while anything is pending. */
export function useQueue(enabled = true) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const timer = useRef<number>();

  const refresh = useCallback(async (): Promise<QueueItem[]> => {
    try {
      const list = await api.get<QueueItem[]>("/queue");
      setItems(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    const tick = async () => {
      const list = await refresh();
      if (stopped) return;
      const pending = list.some((i) => i.status === "queued" || i.status === "processing");
      const visible = document.visibilityState === "visible";
      timer.current = window.setTimeout(tick, pending && visible ? 2500 : 20000);
    };
    tick();
    const onPoke = () => {
      window.clearTimeout(timer.current);
      tick();
    };
    window.addEventListener("collander:queue", onPoke);
    return () => {
      stopped = true;
      window.clearTimeout(timer.current);
      window.removeEventListener("collander:queue", onPoke);
    };
  }, [enabled, refresh]);

  return { items, refresh };
}

export function pokeQueue() {
  window.dispatchEvent(new Event("collander:queue"));
}
