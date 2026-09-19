import { beforeEach, describe, expect, it } from "vitest";

import { useWmStore } from "@/shell/wm/store";

const GEOMETRY = { x: 40, y: 40, w: 400, h: 300 };

beforeEach(() => {
  window.localStorage.clear();
  useWmStore.setState({ windows: {}, topZ: 0 });
});

describe("useWmStore", () => {
  it("open() creates a normal, focused window", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    const win = useWmStore.getState().windows[id];
    expect(win).toBeDefined();
    expect(win.state).toBe("normal");
    expect(win.appId).toBe("dashboard");
    expect(win.z).toBe(useWmStore.getState().topZ);
  });

  it("open() with singleInstance focuses the existing window instead of duplicating", () => {
    const firstId = useWmStore
      .getState()
      .open("dashboard", { title: "Dashboard", geometry: GEOMETRY, singleInstance: true });
    // Focus something else first so the second open() has to actively refocus it.
    useWmStore.getState().open("info-center", { title: "Info Center", geometry: GEOMETRY });

    const secondId = useWmStore
      .getState()
      .open("dashboard", { title: "Dashboard", geometry: GEOMETRY, singleInstance: true });

    expect(secondId).toBe(firstId);
    expect(Object.keys(useWmStore.getState().windows)).toHaveLength(2);
    expect(useWmStore.getState().windows[firstId].z).toBe(useWmStore.getState().topZ);
  });

  it("focus() raises a window's z above the others", () => {
    const a = useWmStore.getState().open("dashboard", { title: "A", geometry: GEOMETRY });
    const b = useWmStore.getState().open("info-center", { title: "B", geometry: GEOMETRY });
    expect(useWmStore.getState().windows[b].z).toBeGreaterThan(useWmStore.getState().windows[a].z);

    useWmStore.getState().focus(a);
    expect(useWmStore.getState().windows[a].z).toBeGreaterThan(useWmStore.getState().windows[b].z);
  });

  it("focus() restores a minimized window to normal", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    useWmStore.getState().minimize(id);
    expect(useWmStore.getState().windows[id].state).toBe("minimized");

    useWmStore.getState().focus(id);
    expect(useWmStore.getState().windows[id].state).toBe("normal");
  });

  it("move() and resize() update geometry", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    useWmStore.getState().move(id, 100, 120);
    useWmStore.getState().resize(id, 500, 350);
    const win = useWmStore.getState().windows[id];
    expect(win.geometry).toEqual({ x: 100, y: 120, w: 500, h: 350 });
  });

  it("move() and resize() are no-ops while maximized", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    useWmStore.getState().toggleMaximize(id);
    useWmStore.getState().move(id, 999, 999);
    useWmStore.getState().resize(id, 999, 999);
    expect(useWmStore.getState().windows[id].geometry).toEqual(GEOMETRY);
  });

  it("toggleMaximize() round-trips back to the original geometry", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    useWmStore.getState().toggleMaximize(id);
    expect(useWmStore.getState().windows[id].state).toBe("maximized");

    useWmStore.getState().toggleMaximize(id);
    const win = useWmStore.getState().windows[id];
    expect(win.state).toBe("normal");
    expect(win.geometry).toEqual(GEOMETRY);
    expect(win.restoreGeometry).toBeNull();
  });

  it("close() removes the window", () => {
    const id = useWmStore.getState().open("dashboard", { title: "Dashboard", geometry: GEOMETRY });
    useWmStore.getState().close(id);
    expect(useWmStore.getState().windows[id]).toBeUndefined();
  });
});
