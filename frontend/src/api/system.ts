import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export interface SystemInfo {
  hostname: string;
  os_pretty_name: string;
  kernel: string;
  nasos_version: string;
  uptime_seconds: number;
}

export function useSystemInfo() {
  return useQuery({
    queryKey: ["system", "info"],
    queryFn: () => api.get<SystemInfo>("/system/info"),
    refetchInterval: 30_000,
  });
}
