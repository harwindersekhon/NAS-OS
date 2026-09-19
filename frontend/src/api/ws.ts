import { useEffect, useState } from "react";

type TopicListener = (data: unknown) => void;

interface WsFrame {
  topic: string;
  data: unknown;
}

function isWsFrame(value: unknown): value is WsFrame {
  return typeof value === "object" && value !== null && "topic" in value && "data" in value;
}

/**
 * One shared WebSocket connection for the whole app (PLAN.md §5: WS topic
 * subscriptions, streams only while windows open). Components subscribe by
 * topic via `useTopic`; the hub ref-counts listeners and only sends
 * subscribe/unsubscribe over the wire on the first/last listener for a topic.
 */
class WsHub {
  private socket: WebSocket | null = null;
  private listeners = new Map<string, Set<TopicListener>>();
  // DOM's setTimeout (always called as window.setTimeout below) returns a
  // number; typed explicitly rather than via ReturnType<> since @types/node
  // (a devDependency, for vite.config.ts) puts its Timeout-returning
  // ambient setTimeout in scope too.
  private reconnectTimer: number | null = null;
  private running = false;

  start(): void {
    if (this.running) return;
    this.running = true;
    this.connect();
  }

  stop(): void {
    this.running = false;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  subscribe(topic: string, listener: TopicListener): () => void {
    let set = this.listeners.get(topic);
    if (!set) {
      set = new Set();
      this.listeners.set(topic, set);
      this.send({ action: "subscribe", topic });
    }
    set.add(listener);

    return () => {
      set.delete(listener);
      if (set.size === 0) {
        this.listeners.delete(topic);
        this.send({ action: "unsubscribe", topic });
      }
    };
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  private connect(): void {
    const url = new URL("/api/v1/ws", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      for (const topic of this.listeners.keys()) {
        this.send({ action: "subscribe", topic });
      }
    });
    socket.addEventListener("message", (event: MessageEvent<string>) => {
      const parsed: unknown = JSON.parse(event.data);
      if (!isWsFrame(parsed)) return;
      const set = this.listeners.get(parsed.topic);
      if (set) {
        for (const listener of set) listener(parsed.data);
      }
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) this.socket = null;
      if (this.running) {
        this.reconnectTimer = window.setTimeout(() => this.connect(), 2000);
      }
    });
    socket.addEventListener("error", () => socket.close());
  }
}

export const wsHub = new WsHub();

/** Latest payload published on `topic`, or null before the first message. */
export function useTopic<T>(topic: string): T | null {
  const [value, setValue] = useState<T | null>(null);

  useEffect(() => wsHub.subscribe(topic, (data) => setValue(data as T)), [topic]);

  return value;
}
