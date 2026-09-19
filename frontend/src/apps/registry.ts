import type { TablerIcon } from "@tabler/icons-react";
import { IconDatabase, IconFolder, IconLayoutDashboard, IconSettings } from "@tabler/icons-react";
import { type ComponentType, lazy } from "react";

export interface AppSize {
  w: number;
  h: number;
}

export interface AppManifest {
  id: string;
  title: string;
  icon: TablerIcon;
  component: ComponentType;
  defaultSize: AppSize;
  minSize: AppSize;
  singleInstance: boolean;
  adminOnly: boolean;
}

const Dashboard = lazy(() =>
  import("./dashboard/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const ControlPanel = lazy(() =>
  import("./control-panel/ControlPanel").then((m) => ({ default: m.ControlPanel })),
);
const FileStation = lazy(() =>
  import("./file-station/FileStation").then((m) => ({ default: m.FileStation })),
);
const StorageManager = lazy(() =>
  import("./storage-manager/StorageManager").then((m) => ({ default: m.StorageManager })),
);

export const appRegistry: AppManifest[] = [
  {
    id: "dashboard",
    title: "Dashboard",
    icon: IconLayoutDashboard,
    component: Dashboard,
    defaultSize: { w: 720, h: 460 },
    minSize: { w: 420, h: 320 },
    singleInstance: true,
    adminOnly: false,
  },
  {
    id: "control-panel",
    title: "Control Panel",
    icon: IconSettings,
    component: ControlPanel,
    defaultSize: { w: 760, h: 520 },
    minSize: { w: 560, h: 400 },
    singleInstance: true,
    adminOnly: false,
  },
  {
    id: "file-station",
    title: "File Station",
    icon: IconFolder,
    component: FileStation,
    defaultSize: { w: 920, h: 600 },
    minSize: { w: 640, h: 420 },
    singleInstance: true,
    adminOnly: false,
  },
  {
    id: "storage-manager",
    title: "Storage Manager",
    icon: IconDatabase,
    component: StorageManager,
    defaultSize: { w: 860, h: 560 },
    minSize: { w: 600, h: 400 },
    singleInstance: true,
    adminOnly: true,
  },
];

export function getApp(id: string): AppManifest | undefined {
  return appRegistry.find((app) => app.id === id);
}
