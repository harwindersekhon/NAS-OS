import { Menu, UnstyledButton } from "@mantine/core";
import { IconGridDots, IconLogout, IconUserCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { useLogout, useSession } from "@/api/auth";
import { useTopic } from "@/api/ws";
import { getApp } from "@/apps/registry";

import { Launcher } from "./Launcher";
import { useWmStore } from "./wm/store";

interface MonitorSample {
  cpu_percent: number;
}

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function Taskbar() {
  const [launcherOpen, setLauncherOpen] = useState(false);
  const windows = useWmStore((s) => s.windows);
  const topZ = useWmStore((s) => s.topZ);
  const focus = useWmStore((s) => s.focus);
  const minimize = useWmStore((s) => s.minimize);
  const sample = useTopic<MonitorSample>("monitor.sample");
  const { data: session } = useSession();
  const logout = useLogout();
  const clock = useClock();

  const entries = Object.values(windows);

  const handleEntryClick = (id: string, z: number, state: string) => {
    if (state !== "minimized" && z === topZ) {
      minimize(id);
    } else {
      focus(id);
    }
  };

  return (
    <div className="nasos-taskbar">
      <div className="nasos-taskbar__section nasos-taskbar__section--start">
        <UnstyledButton
          className="nasos-taskbar__launcher-btn"
          onClick={() => setLauncherOpen((open) => !open)}
          aria-expanded={launcherOpen}
          aria-label="Launcher"
        >
          <IconGridDots size={18} stroke={1.75} />
          <span className="nasos-taskbar__brand">NAS-OS</span>
        </UnstyledButton>
        {launcherOpen && <Launcher onClose={() => setLauncherOpen(false)} />}
      </div>

      <div className="nasos-taskbar__section nasos-taskbar__section--windows">
        {entries.map((win) => {
          const manifest = getApp(win.appId);
          if (!manifest) return null;
          const Icon = manifest.icon;
          const active = win.state !== "minimized" && win.z === topZ;
          return (
            <UnstyledButton
              key={win.id}
              className={`nasos-taskbar__entry${active ? " nasos-taskbar__entry--active" : ""}`}
              onClick={() => handleEntryClick(win.id, win.z, win.state)}
            >
              <Icon size={15} stroke={1.75} />
              <span>{win.title}</span>
            </UnstyledButton>
          );
        })}
      </div>

      <div className="nasos-taskbar__section nasos-taskbar__section--end">
        {sample && (
          <span className="nasos-taskbar__stat" title="CPU usage">
            CPU {Math.round(sample.cpu_percent)}%
          </span>
        )}
        <span className="nasos-taskbar__clock">{clock}</span>
        <Menu position="bottom-end" withArrow>
          <Menu.Target>
            <UnstyledButton className="nasos-taskbar__user" aria-label="User menu">
              <IconUserCircle size={18} stroke={1.75} />
              <span>{session?.username}</span>
            </UnstyledButton>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<IconLogout size={15} stroke={1.75} />}
              onClick={() => logout.mutate()}
            >
              Log out
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>
    </div>
  );
}
