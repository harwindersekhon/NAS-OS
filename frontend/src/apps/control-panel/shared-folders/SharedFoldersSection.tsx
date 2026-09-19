import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle, IconLock, IconPlus, IconTrash } from "@tabler/icons-react";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import {
  useCreateShare,
  useDeleteShare,
  usePermissions,
  useSetPermissions,
  useShares,
} from "@/api/shares";
import type { PermissionEntry, ShareInfo } from "@/api/shares";
import { useRegisterVolume, useVolumes } from "@/api/volumes";
import type { VolumeInfo } from "@/api/volumes";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function RegisterVolumeModal({
  opened,
  onClose,
  onSubmit,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (values: { name: string; mountpoint: string }) => void;
  error: unknown;
}) {
  const [name, setName] = useState("");
  const [mountpoint, setMountpoint] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ name, mountpoint });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Register volume">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            required
            autoFocus
          />
          <TextInput
            label="Mountpoint"
            description="Must already be mounted; not / or /boot"
            placeholder="/mnt/data"
            value={mountpoint}
            onChange={(event) => setMountpoint(event.currentTarget.value)}
            required
          />
          {error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(error)}
            </Alert>
          )}
          <Button type="submit" fullWidth>
            Register
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

function CreateShareModal({
  opened,
  onClose,
  onSubmit,
  volumes,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (values: { name: string; volume_id: number; description: string }) => void;
  volumes: VolumeInfo[];
  error: unknown;
}) {
  const [name, setName] = useState("");
  const [volumeId, setVolumeId] = useState<string | null>(null);
  const [description, setDescription] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!volumeId) return;
    onSubmit({ name, volume_id: Number(volumeId), description });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Create shared folder">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            required
            autoFocus
          />
          <Select
            label="Volume"
            placeholder="Select a volume"
            data={volumes.map((v) => ({
              value: String(v.id),
              label: `${v.name} (${v.mountpoint})`,
            }))}
            value={volumeId}
            onChange={setVolumeId}
            required
          />
          <TextInput
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
          />
          {error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(error)}
            </Alert>
          )}
          <Button type="submit" fullWidth disabled={!volumeId}>
            Create
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

/**
 * Only mounts once `permissions` has loaded (see PermissionsModal below),
 * so `draft`'s lazy initializer always captures real data — no effect
 * needed to sync it in after the fact. Keying this by share id where it's
 * rendered makes switching shares remount it fresh instead of carrying
 * over the previous share's draft.
 */
function PermissionsForm({
  shareId,
  initialPermissions,
  onSaved,
}: {
  shareId: number;
  initialPermissions: PermissionEntry[];
  onSaved: () => void;
}) {
  const setPermissions = useSetPermissions(shareId);
  const [draft, setDraft] = useState<PermissionEntry[]>(initialPermissions);
  const [recursive, setRecursive] = useState(false);

  const updateRow = (index: number, patch: Partial<PermissionEntry>) => {
    setDraft((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeRow = (index: number) => {
    setDraft((rows) => rows.filter((_, i) => i !== index));
  };

  const addRow = () => {
    setDraft((rows) => [...rows, { principal_type: "user", principal: "", level: "rw" }]);
  };

  const handleSave = () => {
    setPermissions.mutate(
      { permissions: draft.filter((row) => row.principal.trim() !== ""), recursive },
      { onSuccess: onSaved },
    );
  };

  return (
    <Stack gap="sm">
      {draft.map((row, index) => (
        <Group key={index} gap="xs" wrap="nowrap">
          <Select
            data={[
              { value: "user", label: "User" },
              { value: "group", label: "Group" },
            ]}
            value={row.principal_type}
            onChange={(value) =>
              updateRow(index, { principal_type: (value as "user" | "group") ?? "user" })
            }
            w={110}
          />
          <TextInput
            placeholder="username or group name"
            value={row.principal}
            onChange={(event) => updateRow(index, { principal: event.currentTarget.value })}
            style={{ flex: 1 }}
          />
          <Select
            data={[
              { value: "rw", label: "Read/write" },
              { value: "ro", label: "Read only" },
            ]}
            value={row.level}
            onChange={(value) => updateRow(index, { level: (value as "rw" | "ro") ?? "rw" })}
            w={140}
          />
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label="Remove"
            onClick={() => removeRow(index)}
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      ))}

      <Button
        variant="default"
        size="xs"
        leftSection={<IconPlus size={14} />}
        onClick={addRow}
        style={{ alignSelf: "flex-start" }}
      >
        Add principal
      </Button>

      <Divider my={4} />

      <Checkbox
        label="Re-apply recursively to existing files (runs as a background job)"
        checked={recursive}
        onChange={(event) => setRecursive(event.currentTarget.checked)}
      />

      {setPermissions.error !== null && (
        <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
          {errorMessage(setPermissions.error)}
        </Alert>
      )}

      <Button onClick={handleSave} loading={setPermissions.isPending}>
        Save permissions
      </Button>
    </Stack>
  );
}

function PermissionsModal({ share, onClose }: { share: ShareInfo | null; onClose: () => void }) {
  const { data: permissions, isLoading } = usePermissions(share?.id ?? -1);

  return (
    <Modal
      opened={share !== null}
      onClose={onClose}
      title={`Permissions: ${share?.name ?? ""}`}
      size="lg"
    >
      {share && !isLoading && permissions ? (
        <PermissionsForm
          key={share.id}
          shareId={share.id}
          initialPermissions={permissions}
          onSaved={onClose}
        />
      ) : (
        <Text size="sm" c="dimmed">
          Loading…
        </Text>
      )}
    </Modal>
  );
}

export function SharedFoldersSection() {
  const { data: volumes, isLoading: volumesLoading } = useVolumes();
  const { data: shares, isLoading: sharesLoading } = useShares();
  const registerVolume = useRegisterVolume();
  const createShare = useCreateShare();
  const deleteShare = useDeleteShare();

  const [registerOpen, setRegisterOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [permissionsTarget, setPermissionsTarget] = useState<ShareInfo | null>(null);

  return (
    <div className="nasos-section">
      <Text fw={600} size="sm" mb={6}>
        Volumes
      </Text>
      <div className="nasos-section__toolbar">
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => setRegisterOpen(true)}
        >
          Register volume
        </Button>
      </div>
      <Table verticalSpacing="xs" mb="lg">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Mountpoint</Table.Th>
            <Table.Th>Filesystem</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!volumesLoading &&
            volumes?.map((volume) => (
              <Table.Tr key={volume.id}>
                <Table.Td>{volume.name}</Table.Td>
                <Table.Td className="nasos-mono">{volume.mountpoint}</Table.Td>
                <Table.Td className="nasos-mono">{volume.filesystem}</Table.Td>
              </Table.Tr>
            ))}
        </Table.Tbody>
      </Table>

      <Text fw={600} size="sm" mb={6}>
        Shared Folders
      </Text>
      <div className="nasos-section__toolbar">
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => setCreateOpen(true)}
          disabled={!volumes || volumes.length === 0}
        >
          Create shared folder
        </Button>
      </div>
      <Table verticalSpacing="xs" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Path</Table.Th>
            <Table.Th>Description</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!sharesLoading &&
            shares?.map((share) => (
              <Table.Tr key={share.id}>
                <Table.Td>{share.name}</Table.Td>
                <Table.Td className="nasos-mono">{share.path}</Table.Td>
                <Table.Td>{share.description || "—"}</Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={`Permissions for ${share.name}`}
                      onClick={() => setPermissionsTarget(share)}
                    >
                      <IconLock size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      color="red"
                      aria-label={`Delete ${share.name}`}
                      onClick={() => deleteShare.mutate({ shareId: share.id, deleteFiles: false })}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
        </Table.Tbody>
      </Table>

      <RegisterVolumeModal
        opened={registerOpen}
        onClose={() => {
          setRegisterOpen(false);
          registerVolume.reset();
        }}
        error={registerVolume.error}
        onSubmit={(values) => {
          registerVolume.mutate(values, { onSuccess: () => setRegisterOpen(false) });
        }}
      />
      <CreateShareModal
        opened={createOpen}
        onClose={() => {
          setCreateOpen(false);
          createShare.reset();
        }}
        volumes={volumes ?? []}
        error={createShare.error}
        onSubmit={(values) => {
          createShare.mutate(values, { onSuccess: () => setCreateOpen(false) });
        }}
      />
      <PermissionsModal share={permissionsTarget} onClose={() => setPermissionsTarget(null)} />
    </div>
  );
}
