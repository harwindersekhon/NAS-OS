import { create } from "zustand";

export type WindowState = "normal" | "minimized" | "maximized";

export interface WindowGeometry {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface WindowInstance {
  id: string;
  appId: string;
  title: string;
  geometry: WindowGeometry;
  /** geometry to return to on un-maximize; null when not currently maximized */
  restoreGeometry: WindowGeometry | null;
  z: number;
  state: WindowState;
}

export interface OpenWindowOptions {
  title: string;
  geometry: WindowGeometry;
  singleInstance?: boolean;
}

interface WmState {
  windows: Record<string, WindowInstance>;
  topZ: number;
  open: (appId: string, options: OpenWindowOptions) => string;
  close: (id: string) => void;
  focus: (id: string) => void;
  move: (id: string, x: number, y: number) => void;
  resize: (id: string, w: number, h: number) => void;
  minimize: (id: string) => void;
  toggleMaximize: (id: string) => void;
}

const GEOMETRY_STORAGE_KEY = "nasos.wm.geometry.v1";
const CASCADE_OFFSET = 28;
const CASCADE_CYCLE = 6;

function loadSavedGeometry(appId: string): WindowGeometry | null {
  try {
    const raw = window.localStorage.getItem(GEOMETRY_STORAGE_KEY);
    const all = raw ? (JSON.parse(raw) as Record<string, WindowGeometry>) : {};
    return all[appId] ?? null;
  } catch {
    return null;
  }
}

function saveGeometry(appId: string, geometry: WindowGeometry): void {
  try {
    const raw = window.localStorage.getItem(GEOMETRY_STORAGE_KEY);
    const all = raw ? (JSON.parse(raw) as Record<string, WindowGeometry>) : {};
    all[appId] = geometry;
    window.localStorage.setItem(GEOMETRY_STORAGE_KEY, JSON.stringify(all));
  } catch {
    // Best-effort only: a remembered window position is a per-viewer
    // convenience, never state the app depends on being there.
  }
}

let nextId = 0;
function makeWindowId(): string {
  nextId += 1;
  return `win-${nextId}-${Date.now().toString(36)}`;
}

export const useWmStore = create<WmState>((set, get) => ({
  windows: {},
  topZ: 0,

  open: (appId, options) => {
    if (options.singleInstance) {
      const existing = Object.values(get().windows).find((w) => w.appId === appId);
      if (existing) {
        get().focus(existing.id);
        return existing.id;
      }
    }

    const id = makeWindowId();
    const openCount = Object.keys(get().windows).length;
    const saved = loadSavedGeometry(appId);
    const geometry = saved ?? {
      ...options.geometry,
      x: options.geometry.x + (openCount % CASCADE_CYCLE) * CASCADE_OFFSET,
      y: options.geometry.y + (openCount % CASCADE_CYCLE) * CASCADE_OFFSET,
    };

    const z = get().topZ + 1;
    set((state) => ({
      topZ: z,
      windows: {
        ...state.windows,
        [id]: {
          id,
          appId,
          title: options.title,
          geometry,
          restoreGeometry: null,
          z,
          state: "normal",
        },
      },
    }));
    return id;
  },

  close: (id) => {
    set((state) => {
      if (!(id in state.windows)) return state;
      const windows = { ...state.windows };
      delete windows[id];
      return { windows };
    });
  },

  focus: (id) => {
    set((state) => {
      const win = state.windows[id];
      if (!win) return state;
      const z = state.topZ + 1;
      return {
        topZ: z,
        windows: {
          ...state.windows,
          [id]: { ...win, z, state: win.state === "minimized" ? "normal" : win.state },
        },
      };
    });
  },

  move: (id, x, y) => {
    set((state) => {
      const win = state.windows[id];
      if (!win || win.state === "maximized") return state;
      const geometry = { ...win.geometry, x, y };
      saveGeometry(win.appId, geometry);
      return { windows: { ...state.windows, [id]: { ...win, geometry } } };
    });
  },

  resize: (id, w, h) => {
    set((state) => {
      const win = state.windows[id];
      if (!win || win.state === "maximized") return state;
      const geometry = { ...win.geometry, w, h };
      saveGeometry(win.appId, geometry);
      return { windows: { ...state.windows, [id]: { ...win, geometry } } };
    });
  },

  minimize: (id) => {
    set((state) => {
      const win = state.windows[id];
      if (!win) return state;
      return { windows: { ...state.windows, [id]: { ...win, state: "minimized" } } };
    });
  },

  toggleMaximize: (id) => {
    set((state) => {
      const win = state.windows[id];
      if (!win) return state;
      if (win.state === "maximized") {
        const geometry = win.restoreGeometry ?? win.geometry;
        return {
          windows: {
            ...state.windows,
            [id]: { ...win, state: "normal", geometry, restoreGeometry: null },
          },
        };
      }
      return {
        windows: {
          ...state.windows,
          [id]: { ...win, state: "maximized", restoreGeometry: win.geometry },
        },
      };
    });
  },
}));
