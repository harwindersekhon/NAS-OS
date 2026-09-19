import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface GroupInfo {
  gid: number;
  name: string;
  description: string;
  created_by_nasos: boolean;
}

const groupsKey = ["groups"] as const;

export function useGroups() {
  return useQuery({
    queryKey: groupsKey,
    queryFn: () => api.get<GroupInfo[]>("/groups"),
  });
}

export function useCreateGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description: string }) =>
      api.post<GroupInfo>("/groups", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: groupsKey }),
  });
}

export function useDeleteGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (gid: number) => api.del<{ ok: boolean }>(`/groups/${gid}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: groupsKey }),
  });
}

export function useAddGroupMember() {
  return useMutation({
    mutationFn: ({ gid, username }: { gid: number; username: string }) =>
      api.post<{ ok: boolean }>(`/groups/${gid}/members`, { username }),
  });
}

export function useRemoveGroupMember() {
  return useMutation({
    mutationFn: ({ gid, username }: { gid: number; username: string }) =>
      api.del<{ ok: boolean }>(`/groups/${gid}/members/${username}`),
  });
}
