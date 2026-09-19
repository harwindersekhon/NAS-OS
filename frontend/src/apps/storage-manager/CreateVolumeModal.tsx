import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Progress,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import type { DiskNode, Filesystem, Plan, RaidLevel } from "@/api/storage";
import { useCreatePlan, useExecutePlan } from "@/api/storage";
import { useTopic } from "@/api/ws";
import { ByteSize } from "@/components/ByteSize";
import { ConfirmDangerModal } from "@/components/ConfirmDangerModal";

const LEVEL_OPTIONS: { value: RaidLevel; label: string; minDisks: number }[] = [
  { value: "basic", label: "Basic (single disk, no redundancy)", minDisks: 1 },
  { value: "1", label: "RAID 1 (mirror)", minDisks: 2 },
  { value: "5", label: "RAID 5", minDisks: 3 },
  { value: "6", label: "RAID 6", minDisks: 4 },
  { value: "10", label: "RAID 10", minDisks: 4 },
];

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

interface JobProgress {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message: string;
}

function DiskPicker({
  disks,
  selected,
  onToggle,
}: {
  disks: DiskNode[];
  selected: Set<string>;
  onToggle: (serial: string) => void;
}) {
  const available = disks.filter((d) => d.serial);
  if (available.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No disks found.
      </Text>
    );
  }
  return (
    <Stack gap={6}>
      {available.map((disk) => (
        <Group key={disk.serial} gap="xs" wrap="nowrap" className="nasos-storage-disk-row">
          <Checkbox
            checked={disk.serial !== null && selected.has(disk.serial)}
            disabled={disk.protected}
            onChange={() => disk.serial && onToggle(disk.serial)}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text size="sm" className="nasos-mono">
                {disk.path}
              </Text>
              <Text size="xs" c="dimmed">
                {disk.model ?? "Unknown model"}
              </Text>
            </Group>
            {disk.protected && (
              <Text size="xs" c="red">
                {disk.protected_reason ?? "In use"}
              </Text>
            )}
          </div>
          <ByteSize value={disk.size} />
        </Group>
      ))}
    </Stack>
  );
}

export function CreateVolumeModal({
  opened,
  onClose,
  disks,
}: {
  opened: boolean;
  onClose: () => void;
  disks: DiskNode[];
}) {
  const [name, setName] = useState("");
  const [level, setLevel] = useState<RaidLevel>("basic");
  const [filesystem, setFilesystem] = useState<Filesystem>("xfs");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<Plan | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const createPlan = useCreatePlan();
  const executePlan = useExecutePlan();
  const jobEvent = useTopic<JobProgress>("job.progress");

  const activeJob = jobId && jobEvent?.id === jobId ? jobEvent : null;

  const reset = () => {
    setName("");
    setLevel("basic");
    setFilesystem("xfs");
    setSelected(new Set());
    setPlan(null);
    setJobId(null);
    createPlan.reset();
    executePlan.reset();
  };

  const toggleDisk = (serial: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const levelInfo = LEVEL_OPTIONS.find((l) => l.value === level);
  const enoughDisks = levelInfo ? selected.size >= levelInfo.minDisks : false;
  const exactDiskCount = level === "basic" ? selected.size === 1 : enoughDisks;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    createPlan.mutate(
      { volume_name: name, level, filesystem, disk_serials: [...selected] },
      { onSuccess: setPlan },
    );
  };

  const handleExecute = () => {
    if (!plan) return;
    executePlan.mutate(
      { planId: plan.id, confirmToken: plan.confirm_token, typedConfirmation: plan.confirm_text },
      { onSuccess: (result) => setJobId(result.job_id) },
    );
  };

  if (jobId) {
    return (
      <Modal opened={opened} onClose={() => {}} title="Creating volume" size="md" withCloseButton={false}>
        <Stack gap="sm">
          <Progress value={(activeJob?.progress ?? 0) * 100} animated={activeJob?.status === "running"} />
          {activeJob?.status !== "done" && activeJob?.status !== "failed" && (
            <Text size="sm" c="dimmed">
              {activeJob?.message ?? "Starting…"}
            </Text>
          )}
          {activeJob?.status === "done" && (
            <>
              <Text size="sm">
                Volume {plan?.volume_name ? `"${plan.volume_name}"` : ""} created and mounted.
              </Text>
              <Badge color="green">Done</Badge>
              <Button
                fullWidth
                onClick={() => {
                  reset();
                  onClose();
                }}
              >
                Close
              </Button>
            </>
          )}
          {activeJob?.status === "failed" && (
            <>
              <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
                {activeJob.message}
              </Alert>
              <Button
                fullWidth
                variant="default"
                onClick={() => {
                  reset();
                  onClose();
                }}
              >
                Close
              </Button>
            </>
          )}
        </Stack>
      </Modal>
    );
  }

  if (plan) {
    return (
      <ConfirmDangerModal
        opened={opened}
        onClose={() => setPlan(null)}
        title={`Create volume "${plan.volume_name}"`}
        confirmText={plan.confirm_text}
        confirmLabel="Create volume"
        loading={executePlan.isPending}
        error={executePlan.error}
        onConfirm={handleExecute}
        description={
          <Stack gap={6}>
            <Text size="sm">{plan.data_loss_summary}</Text>
            <div className="nasos-storage-plan-steps">
              {plan.steps.map((step, index) => (
                <div key={index} className="nasos-storage-plan-step">
                  <Text size="xs" c="dimmed">
                    {step.description}
                  </Text>
                  {step.argv.length > 0 && (
                    <Text size="xs" className="nasos-mono nasos-storage-plan-argv">
                      $ {step.argv.join(" ")}
                    </Text>
                  )}
                </div>
              ))}
            </div>
          </Stack>
        }
      />
    );
  }

  return (
    <Modal
      opened={opened}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Create volume"
      size="lg"
    >
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            description="Becomes the mountpoint and RAID/LVM names, e.g. /volume2"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            required
            autoFocus
          />
          <Select
            label="Type"
            data={LEVEL_OPTIONS.map((l) => ({ value: l.value, label: l.label }))}
            value={level}
            onChange={(value) => value && setLevel(value as RaidLevel)}
          />
          <Select
            label="Filesystem"
            data={[
              { value: "xfs", label: "XFS" },
              { value: "ext4", label: "ext4" },
            ]}
            value={filesystem}
            onChange={(value) => value && setFilesystem(value as Filesystem)}
          />
          <Text size="sm" fw={500}>
            Disks ({levelInfo ? `${levelInfo.minDisks}+ needed` : ""})
          </Text>
          <DiskPicker disks={disks} selected={selected} onToggle={toggleDisk} />
          {createPlan.error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(createPlan.error)}
            </Alert>
          )}
          <Button type="submit" fullWidth disabled={!exactDiskCount || !name} loading={createPlan.isPending}>
            Review plan
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
