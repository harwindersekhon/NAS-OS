import { IconFolder, IconInfoCircle, IconUsers, IconUsersGroup } from "@tabler/icons-react";
import { lazy, Suspense, useState } from "react";
import type { ComponentType } from "react";

const InfoSection = lazy(() =>
  import("./info/InfoSection").then((m) => ({ default: m.InfoSection })),
);
const UsersSection = lazy(() =>
  import("./users/UsersSection").then((m) => ({ default: m.UsersSection })),
);
const GroupsSection = lazy(() =>
  import("./groups/GroupsSection").then((m) => ({ default: m.GroupsSection })),
);
const SharedFoldersSection = lazy(() =>
  import("./shared-folders/SharedFoldersSection").then((m) => ({
    default: m.SharedFoldersSection,
  })),
);

interface SectionDef {
  id: string;
  label: string;
  icon: typeof IconInfoCircle;
  component: ComponentType;
}

const SECTIONS: SectionDef[] = [
  { id: "info", label: "Info Center", icon: IconInfoCircle, component: InfoSection },
  { id: "users", label: "Users", icon: IconUsers, component: UsersSection },
  { id: "groups", label: "Groups", icon: IconUsersGroup, component: GroupsSection },
  {
    id: "shared-folders",
    label: "Shared Folders",
    icon: IconFolder,
    component: SharedFoldersSection,
  },
];

export function ControlPanel() {
  const [activeId, setActiveId] = useState(SECTIONS[0].id);
  const active = SECTIONS.find((s) => s.id === activeId) ?? SECTIONS[0];
  const ActiveComponent = active.component;

  return (
    <div className="nasos-control-panel">
      <nav className="nasos-control-panel__sidebar">
        {SECTIONS.map((section) => {
          const Icon = section.icon;
          return (
            <button
              key={section.id}
              type="button"
              className={`nasos-control-panel__nav-item${
                section.id === activeId ? " nasos-control-panel__nav-item--active" : ""
              }`}
              onClick={() => setActiveId(section.id)}
            >
              <Icon size={16} stroke={1.75} />
              <span>{section.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="nasos-control-panel__content">
        <Suspense fallback={<div className="nasos-window__loading">Loading…</div>}>
          <ActiveComponent />
        </Suspense>
      </div>
    </div>
  );
}
