import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface VolumeInfo {
  id: number;
  name: string;
  mountpoint: string;
  filesystem: string;
  managed: boolean;
  raid_level: string | null;
}

const volumesKey = ["volumes"] as const;

export function useVolumes() {
  return useQuery({
    queryKey: volumesKey,
    queryFn: () => api.get<VolumeInfo[]>("/volumes"),
    refetchInterval: 30_000,
  });
}

export function useRegisterVolume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; mountpoint: string }) =>
      api.post<VolumeInfo>("/volumes", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: volumesKey }),
  });
}
