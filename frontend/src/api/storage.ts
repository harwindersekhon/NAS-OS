import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type StorageHealth = "ok" | "warning" | "critical" | "unknown";
export type RaidLevel = "basic" | "1" | "5" | "6" | "10";
export type Filesystem = "xfs" | "ext4";

export interface DiskSmart {
  health: StorageHealth;
  temperature_c: number | null;
  power_on_hours: number | null;
}

export interface DiskNode {
  name: string;
  path: string;
  type: string;
  serial: string | null;
  model: string | null;
  wwn: string | null;
  size: number;
  rota: boolean;
  transport: string;
  fstype: string | null;
  mountpoint: string | null;
  uuid: string | null;
  smart: DiskSmart | null;
  protected: boolean;
  protected_reason: string | null;
  children: DiskNode[];
}

export interface ArrayInfo {
  path: string;
  name: string;
  level: string;
  devices: string[];
  state: string;
  resync_percent: number | null;
}

export interface StorageInventory {
  disks: DiskNode[];
  arrays: ArrayInfo[];
  vgs: { name: string; pvs: string[]; size: number; free: number }[];
  lvs: { name: string; vg: string; path: string; size: number }[];
}

export interface PlanStep {
  description: string;
  op: string;
  argv: string[];
}

export interface Plan {
  id: string;
  steps: PlanStep[];
  confirm_token: string;
  confirm_text: string;
  data_loss_summary: string;
  expires_at: number;
  volume_name: string;
  mountpoint: string;
}

export interface CreatePlanRequest {
  volume_name: string;
  level: RaidLevel;
  filesystem: Filesystem;
  disk_serials: string[];
}

const inventoryKey = ["storage", "inventory"] as const;

export function useStorageInventory() {
  return useQuery({
    queryKey: inventoryKey,
    queryFn: () => api.get<StorageInventory>("/storage/inventory"),
    refetchInterval: 30_000,
  });
}

export function useCreatePlan() {
  return useMutation({
    mutationFn: (body: CreatePlanRequest) => api.post<Plan>("/storage/plans", body),
  });
}

export function useExecutePlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      planId,
      confirmToken,
      typedConfirmation,
    }: {
      planId: string;
      confirmToken: string;
      typedConfirmation: string;
    }) =>
      api.post<{ job_id: string | null }>(`/storage/plans/${planId}/execute`, {
        confirm_token: confirmToken,
        typed_confirmation: typedConfirmation,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inventoryKey }),
  });
}

/** Flattens the disk tree into every physical disk (top level of
 * `inventory.disks` — lsblk's own tree already puts only whole disks
 * there, partitions/arrays/LVs live under `children`). */
export function physicalDisks(inventory: StorageInventory | undefined): DiskNode[] {
  return inventory?.disks ?? [];
}
