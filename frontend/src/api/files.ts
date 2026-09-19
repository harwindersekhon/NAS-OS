import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  mtime: number;
  owner_uid: number;
}

export interface RootEntry {
  id: number;
  name: string;
  path: string;
}

export interface FileProperties {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  mtime: number;
  owner_uid: number;
  owner_name: string;
  mode: string;
  item_count: number | null;
}

export type AclKind = "user" | "group";
export type AclLevel = "rw" | "ro";

export interface FileAclEntry {
  kind: AclKind;
  numeric_id: number;
  level: AclLevel;
}

export interface JobRecord {
  id: string;
  kind: string;
  resource: string | null;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message: string;
}

const rootsKey = ["files", "roots"] as const;
const listKey = (path: string) => ["files", "list", path] as const;
const jobsKey = ["files", "jobs"] as const;

export function useRoots() {
  return useQuery({
    queryKey: rootsKey,
    queryFn: () => api.get<RootEntry[]>("/files/roots"),
  });
}

export function useFileList(path: string | null) {
  return useQuery({
    queryKey: listKey(path ?? ""),
    queryFn: () => api.get<{ entries: FileEntry[] }>(`/files/list?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
  });
}

export function useSearch(path: string | null, query: string) {
  return useQuery({
    queryKey: ["files", "search", path, query] as const,
    queryFn: () =>
      api.get<{ entries: FileEntry[] }>(
        `/files/search?path=${encodeURIComponent(path!)}&query=${encodeURIComponent(query)}`,
      ),
    enabled: path !== null && query.trim().length > 0,
  });
}

export function useProperties(path: string | null) {
  return useQuery({
    queryKey: ["files", "properties", path] as const,
    queryFn: () => api.get<FileProperties>(`/files/properties?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
  });
}

export function useAcl(path: string | null) {
  return useQuery({
    queryKey: ["files", "acl", path] as const,
    queryFn: () => api.get<{ entries: FileAclEntry[] }>(`/files/acl?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
  });
}

export function useSetAcl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { path: string; entries: FileAclEntry[]; recursive: boolean }) =>
      api.put<{ job_id: string | null }>("/files/acl", body),
    onSuccess: (_data, vars) =>
      queryClient.invalidateQueries({ queryKey: ["files", "acl", vars.path] }),
  });
}

function useInvalidateListing() {
  const queryClient = useQueryClient();
  return (path: string) => queryClient.invalidateQueries({ queryKey: listKey(path) });
}

export function useMkdir(path: string) {
  const invalidate = useInvalidateListing();
  return useMutation({
    mutationFn: (name: string) => api.post<{ ok: boolean }>("/files/mkdir", { path: `${path}/${name}` }),
    onSuccess: () => invalidate(path),
  });
}

export function useRename(path: string) {
  const invalidate = useInvalidateListing();
  return useMutation({
    mutationFn: (vars: { path: string; new_name: string }) =>
      api.post<{ ok: boolean }>("/files/rename", vars),
    onSuccess: () => invalidate(path),
  });
}

export function useDelete(path: string) {
  const invalidate = useInvalidateListing();
  return useMutation({
    mutationFn: (paths: string[]) =>
      api.post<{ job_id: string | null }>("/files/delete", { paths }),
    onSuccess: () => invalidate(path),
  });
}

export function useCopy(path: string) {
  const invalidate = useInvalidateListing();
  return useMutation({
    mutationFn: (vars: { sources: string[]; dest_dir: string }) =>
      api.post<{ job_id: string | null }>("/files/copy", vars),
    onSuccess: (_data, vars) => {
      void invalidate(path);
      void invalidate(vars.dest_dir);
    },
  });
}

export function useMove(path: string) {
  const invalidate = useInvalidateListing();
  return useMutation({
    mutationFn: (vars: { sources: string[]; dest_dir: string }) =>
      api.post<{ job_id: string | null }>("/files/move", vars),
    onSuccess: (_data, vars) => {
      void invalidate(path);
      void invalidate(vars.dest_dir);
    },
  });
}

export function useZip() {
  return useMutation({
    mutationFn: (sources: string[]) =>
      api.post<{ job_id: string | null; dest_path: string }>("/files/zip", { sources }),
  });
}

export function useJobs(enabled: boolean) {
  return useQuery({
    queryKey: jobsKey,
    queryFn: () => api.get<{ jobs: JobRecord[] }>("/files/jobs"),
    enabled,
    refetchInterval: enabled ? 500 : false,
  });
}

export function contentUrl(path: string, disposition: "inline" | "attachment" = "inline"): string {
  return `/api/v1/files/content?path=${encodeURIComponent(path)}&disposition=${disposition}`;
}
