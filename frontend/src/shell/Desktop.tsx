import { useEffect } from "react";

import { getApp } from "@/apps/registry";

import { Window } from "./wm/Window";
import { useWmStore } from "./wm/store";

export function Desktop() {
  const windows = useWmStore((s) => s.windows);
  const topZ = useWmStore((s) => s.topZ);
  const open = useWmStore((s) => s.open);

  const instances = Object.values(windows);

  // Land on the Dashboard rather than an empty desktop after a fresh login.
  useEffect(() => {
    if (Object.keys(useWmStore.getState().windows).length > 0) return;
    const manifest = getApp("dashboard");
    if (!manifest) return;
    open("dashboard", {
      title: manifest.title,
      geometry: { x: 96, y: 72, w: manifest.defaultSize.w, h: manifest.defaultSize.h },
      singleInstance: manifest.singleInstance,
    });
    // Runs once per Desktop mount (i.e. once per login session) by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="nasos-desktop nasos-canvas-texture">
      {instances.map((win) => {
        const manifest = getApp(win.appId);
        if (!manifest) return null;
        return <Window key={win.id} win={win} manifest={manifest} isFocused={win.z === topZ} />;
      })}
    </div>
  );
}
