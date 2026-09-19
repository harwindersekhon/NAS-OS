import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "./client";

export interface SessionInfo {
  username: string;
  role: "admin" | "user";
  uid: number;
}

export const sessionQueryKey = ["auth", "me"] as const;

const authApi = {
  login: (username: string, password: string) =>
    api.post<SessionInfo>("/auth/login", { username, password }),
  logout: () => api.post<{ ok: boolean }>("/auth/logout"),
  me: () => api.get<SessionInfo>("/auth/me"),
};

/** data === null means confirmed unauthenticated (401), not "still loading". */
export function useSession() {
  return useQuery<SessionInfo | null, ApiError>({
    queryKey: sessionQueryKey,
    queryFn: async () => {
      try {
        return await authApi.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          return null;
        }
        throw err;
      }
    },
    retry: false,
    staleTime: Infinity,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authApi.login(username, password),
    onSuccess: (session) => {
      queryClient.setQueryData(sessionQueryKey, session);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      queryClient.setQueryData<SessionInfo | null>(sessionQueryKey, null);
    },
  });
}
