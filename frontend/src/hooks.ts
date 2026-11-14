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

const WAKE_KEY = "collander:keep-screen-on";

/**
 * Keep the screen on while a page is open, if the person asked for it on this device.
 *
 * Browsers drop the lock whenever the page is hidden (switching apps, locking the phone),
 * so it is taken again each time the page becomes visible. Only available over HTTPS.
 */
export function useWakeLock() {
  const supported = typeof navigator !== "undefined" && "wakeLock" in navigator;
  const [wanted, setWanted] = useState(() => {
    try {
      return localStorage.getItem(WAKE_KEY) === "on";
    } catch {
      return false;
    }
  });
  const [active, setActive] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const sentinel = useRef<WakeLockSentinel | null>(null);
  const pending = useRef(false);

  useEffect(() => {
    if (!supported || !wanted) return;
    let stopped = false;
    const acquire = async () => {
      if (stopped || sentinel.current || pending.current) return;
      if (document.visibilityState !== "visible") return;
      pending.current = true;
      try {
        const s = await navigator.wakeLock.request("screen");
        if (stopped) {
          s.release();
          return;
        }
        sentinel.current = s;
        setActive(true);
        s.addEventListener("release", () => {
          if (sentinel.current === s) {
            sentinel.current = null;
            setActive(false);
          }
        });
      } catch {
        setActive(false); // refused (e.g. low battery); tapping the button tries again
      } finally {
        pending.current = false;
      }
    };
    acquire();
    const onVisible = () => {
      if (document.visibilityState === "visible") acquire();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      const s = sentinel.current;
      sentinel.current = null;
      s?.release();
      setActive(false);
    };
  }, [supported, wanted, attempt]);

  const remember = (on: boolean) => {
    setWanted(on);
    try {
      localStorage.setItem(WAKE_KEY, on ? "on" : "off");
    } catch {
      /* private mode: works for this visit only */
    }
  };

  /** Turn it off if it's on; otherwise turn it on (or retry if the browser refused). */
  const toggle = () => {
    if (active) remember(false);
    else if (wanted) setAttempt((n) => n + 1);
    else remember(true);
  };

  return { supported, active, toggle };
}
