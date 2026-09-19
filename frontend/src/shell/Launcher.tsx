import { useClickOutside } from "@mantine/hooks";

import { useSession } from "@/api/auth";
import { appRegistry } from "@/apps/registry";

import { useWmStore } from "./wm/store";

interface LauncherProps {
  onClose: () => void;
}

export function Launcher({ onClose }: LauncherProps) {
  const ref = useClickOutside(onClose);
  const open = useWmStore((s) => s.open);
  const { data: session } = useSession();

  const apps = appRegistry.filter((app) => !app.adminOnly || session?.role === "admin");

  const handleLaunch = (appId: string) => {
    const manifest = appRegistry.find((app) => app.id === appId);
    if (!manifest) return;
    open(appId, {
      title: manifest.title,
      geometry: { x: 96, y: 72, w: manifest.defaultSize.w, h: manifest.defaultSize.h },
      singleInstance: manifest.singleInstance,
    });
    onClose();
  };

  return (
    <div className="nasos-launcher" ref={ref}>
      <div className="nasos-launcher__grid">
        {apps.map((app) => {
          const Icon = app.icon;
          return (
            <button
              key={app.id}
              type="button"
              className="nasos-launcher__tile"
              onClick={() => handleLaunch(app.id)}
            >
              <Icon size={26} stroke={1.5} />
              <span>{app.title}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
