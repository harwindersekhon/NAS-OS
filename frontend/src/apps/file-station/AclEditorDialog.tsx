import { ActionIcon, Alert, Button, Checkbox, Divider, Group, Modal, Select, Stack, Text, TextInput } from "@mantine/core";
import { IconAlertCircle, IconPlus, IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { ApiError } from "@/api/client";
import { useAcl, useSetAcl } from "@/api/files";
import type { FileAclEntry } from "@/api/files";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

/** Mirrors control-panel/shared-folders/SharedFoldersSection.tsx's
 * PermissionsForm — same shape (kind/numeric_id/level), just targeting an
 * arbitrary File Station path instead of always a share root. Only mounts
 * once `initialEntries` has loaded, so its lazy useState initializer
 * always captures real data (see AclEditorDialog below). */
function AclEditorForm({
  path,
  initialEntries,
  onSaved,
}: {
  path: string;
  initialEntries: FileAclEntry[];
  onSaved: () => void;
}) {
  const setAcl = useSetAcl();
  const [draft, setDraft] = useState<FileAclEntry[]>(initialEntries);
  const [recursive, setRecursive] = useState(false);

  const updateRow = (index: number, patch: Partial<FileAclEntry>) => {
    setDraft((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };
  const removeRow = (index: number) => setDraft((rows) => rows.filter((_, i) => i !== index));
  const addRow = () => setDraft((rows) => [...rows, { kind: "user", numeric_id: 0, level: "rw" }]);

  const handleSave = () => {
    setAcl.mutate(
      { path, entries: draft.filter((row) => row.numeric_id > 0), recursive },
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
            value={row.kind}
            onChange={(value) => updateRow(index, { kind: (value as "user" | "group") ?? "user" })}
            w={100}
          />
          <TextInput
            placeholder="numeric uid/gid"
            type="number"
            value={row.numeric_id || ""}
            onChange={(event) => updateRow(index, { numeric_id: Number(event.currentTarget.value) })}
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
          <ActionIcon variant="subtle" color="red" aria-label="Remove" onClick={() => removeRow(index)}>
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
        label="Apply recursively to existing contents (runs as a background job)"
        checked={recursive}
        onChange={(event) => setRecursive(event.currentTarget.checked)}
      />

      {setAcl.error !== null && (
        <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
          {errorMessage(setAcl.error)}
        </Alert>
      )}

      <Button onClick={handleSave} loading={setAcl.isPending}>
        Save permissions
      </Button>
    </Stack>
  );
}

export function AclEditorDialog({ path, onClose }: { path: string | null; onClose: () => void }) {
  const { data, isLoading } = useAcl(path);

  return (
    <Modal opened={path !== null} onClose={onClose} title="Permissions" size="lg">
      {path && !isLoading && data ? (
        <AclEditorForm key={path} path={path} initialEntries={data.entries} onSaved={onClose} />
      ) : (
        <Text size="sm" c="dimmed">
          Loading…
        </Text>
      )}
    </Modal>
  );
}
