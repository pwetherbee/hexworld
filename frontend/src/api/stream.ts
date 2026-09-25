import { useEffect } from "react";
import { useStore } from "../store";
import type { Event as HwEvent } from "./types.gen";

/** Live event stream for the open world. Reconnects with backoff and resumes after the last
 * event id it has seen, so nothing is missed or duplicated across drops. */
export function useWorldStream(worldId: string | undefined) {
  useEffect(() => {
    if (!worldId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: number | undefined;

    const connect = () => {
      const { lastEventId, setStreamState, applyEvent } = useStore.getState();
      setStreamState("connecting");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/worlds/${worldId}/stream?after=${lastEventId}`);
      ws.onopen = () => {
        retry = 0;
        setStreamState("open");
      };
      ws.onmessage = (m) => applyEvent(JSON.parse(m.data) as HwEvent);
      ws.onclose = () => {
        setStreamState("closed");
        if (closed) return;
        retry = Math.min(retry + 1, 6);
        timer = window.setTimeout(connect, 250 * 2 ** retry);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [worldId]);
}
