import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface ShareInfo {
  id: number;
  name: string;
  volume_id: number;
  path: string;
  description: string;
  smb_enabled: boolean;
}

export type PrincipalKind = "user" | "group";
export type AclLevel = "rw" | "ro";

export interface PermissionEntry {
  principal_type: PrincipalKind;
  principal: string;
  level: AclLevel;
}

const sharesKey = ["shares"] as const;
const permissionsKey = (shareId: number) => ["shares", shareId, "permissions"] as const;

export function useShares() {
  return useQuery({
    queryKey: sharesKey,
    queryFn: () => api.get<ShareInfo[]>("/shares"),
  });
}

export function useCreateShare() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; volume_id: number; description: string }) =>
      api.post<ShareInfo>("/shares", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey }),
  });
}

export function useDeleteShare() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ shareId, deleteFiles }: { shareId: number; deleteFiles: boolean }) =>
      api.del<{ ok: boolean }>(`/shares/${shareId}?delete_files=${deleteFiles ? "true" : "false"}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey }),
  });
}

export function usePermissions(shareId: number) {
  return useQuery({
    queryKey: permissionsKey(shareId),
    queryFn: () => api.get<PermissionEntry[]>(`/shares/${shareId}/permissions`),
  });
}

export function useSetPermissions(shareId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { permissions: PermissionEntry[]; recursive: boolean }) =>
      api.put<{ job_id: string | null }>(`/shares/${shareId}/permissions`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: permissionsKey(shareId) }),
  });
}
