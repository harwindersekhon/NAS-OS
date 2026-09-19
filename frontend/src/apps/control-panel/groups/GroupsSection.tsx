import { ActionIcon, Alert, Button, Group, Modal, Stack, Table, TextInput } from "@mantine/core";
import { IconAlertCircle, IconPlus, IconTrash, IconUsers } from "@tabler/icons-react";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import {
  useAddGroupMember,
  useCreateGroup,
  useDeleteGroup,
  useGroups,
  useRemoveGroupMember,
} from "@/api/groups";
import type { GroupInfo } from "@/api/groups";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function CreateGroupModal({
  opened,
  onClose,
  onSubmit,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (values: { name: string; description: string }) => void;
  error: unknown;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ name, description });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Create group">
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
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
          />
          {error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(error)}
            </Alert>
          )}
          <Button type="submit" fullWidth>
            Create
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

function MembersModal({ group, onClose }: { group: GroupInfo | null; onClose: () => void }) {
  const [username, setUsername] = useState("");
  const addMember = useAddGroupMember();
  const removeMember = useRemoveGroupMember();

  const handleAdd = (event: FormEvent) => {
    event.preventDefault();
    if (!group || !username) return;
    addMember.mutate({ gid: group.gid, username }, { onSuccess: () => setUsername("") });
  };

  return (
    <Modal opened={group !== null} onClose={onClose} title={`Members: ${group?.name ?? ""}`}>
      <form onSubmit={handleAdd}>
        <Stack gap="sm">
          <TextInput
            label="Add username"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            autoFocus
          />
          {addMember.error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(addMember.error)}
            </Alert>
          )}
          <Button type="submit" size="xs">
            Add
          </Button>
        </Stack>
      </form>
      {removeMember.error !== null && (
        <Alert color="red" mt="sm" icon={<IconAlertCircle size={16} />} variant="light">
          {errorMessage(removeMember.error)}
        </Alert>
      )}
    </Modal>
  );
}

export function GroupsSection() {
  const { data: groups, isLoading } = useGroups();
  const createGroup = useCreateGroup();
  const deleteGroup = useDeleteGroup();

  const [createOpen, setCreateOpen] = useState(false);
  const [membersTarget, setMembersTarget] = useState<GroupInfo | null>(null);

  return (
    <div className="nasos-section">
      <div className="nasos-section__toolbar">
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreateOpen(true)}>
          Create group
        </Button>
      </div>

      <Table verticalSpacing="xs" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Description</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!isLoading &&
            groups?.map((group) => (
              <Table.Tr key={group.gid}>
                <Table.Td className="nasos-mono">{group.name}</Table.Td>
                <Table.Td>{group.description || "—"}</Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={`Manage members of ${group.name}`}
                      onClick={() => setMembersTarget(group)}
                    >
                      <IconUsers size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      color="red"
                      aria-label={`Delete ${group.name}`}
                      onClick={() => deleteGroup.mutate(group.gid)}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
        </Table.Tbody>
      </Table>

      <CreateGroupModal
        opened={createOpen}
        onClose={() => {
          setCreateOpen(false);
          createGroup.reset();
        }}
        error={createGroup.error}
        onSubmit={(values) => {
          createGroup.mutate(values, { onSuccess: () => setCreateOpen(false) });
        }}
      />
      <MembersModal group={membersTarget} onClose={() => setMembersTarget(null)} />
    </div>
  );
}
