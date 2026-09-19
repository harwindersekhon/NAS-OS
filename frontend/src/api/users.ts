import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface UserInfo {
  uid: number;
  username: string;
  description: string;
  smb_enabled: boolean;
  ftp_enabled: boolean;
  created_by_nasos: boolean;
  smb_password_synced: boolean;
}

const usersKey = ["users"] as const;

export function useUsers() {
  return useQuery({
    queryKey: usersKey,
    queryFn: () => api.get<UserInfo[]>("/users"),
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string; description: string }) =>
      api.post<UserInfo>("/users", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey }),
  });
}

export function useImportUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; description: string }) =>
      api.post<UserInfo>("/users/import", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey }),
  });
}

export function useSetUserSmbEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ uid, smbEnabled }: { uid: number; smbEnabled: boolean }) =>
      api.patch<UserInfo>(`/users/${uid}`, { smb_enabled: smbEnabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey }),
  });
}

export function useSetUserPassword() {
  return useMutation({
    mutationFn: ({ uid, password }: { uid: number; password: string }) =>
      api.post<UserInfo>(`/users/${uid}/password`, { password }),
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ uid, deleteHome }: { uid: number; deleteHome: boolean }) =>
      api.del<{ ok: boolean }>(`/users/${uid}?delete_home=${deleteHome ? "true" : "false"}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: usersKey }),
  });
}
