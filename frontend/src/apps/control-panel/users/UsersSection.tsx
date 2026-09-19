import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Switch,
  Table,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle, IconKey, IconPlus, IconTrash, IconUserPlus } from "@tabler/icons-react";
import { type FormEvent, useState } from "react";

import { ApiError } from "@/api/client";
import {
  useCreateUser,
  useDeleteUser,
  useImportUser,
  useSetUserPassword,
  useSetUserSmbEnabled,
  useUsers,
} from "@/api/users";
import type { UserInfo } from "@/api/users";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

interface CreateUserValues {
  username: string;
  password: string;
  description: string;
}

function CreateUserModal({
  opened,
  onClose,
  onSubmit,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (values: CreateUserValues) => void;
  error: unknown;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ username, password, description });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Create user">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Username"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            required
            autoFocus
          />
          <PasswordInput
            label="Password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
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
          <Button type="submit" fullWidth>
            Create
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

function ImportUserModal({
  opened,
  onClose,
  onSubmit,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (values: { username: string; description: string }) => void;
  error: unknown;
}) {
  const [username, setUsername] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ username, description });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Import existing account">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Username"
            description="An existing POSIX account on this server"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
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
            Import
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

function SetPasswordModal({
  user,
  onClose,
  onSubmit,
  error,
}: {
  user: UserInfo | null;
  onClose: () => void;
  onSubmit: (password: string) => void;
  error: unknown;
}) {
  const [password, setPassword] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(password);
  };

  return (
    <Modal opened={user !== null} onClose={onClose} title={`Set password: ${user?.username ?? ""}`}>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <PasswordInput
            label="New password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            required
            autoFocus
          />
          {error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(error)}
            </Alert>
          )}
          <Button type="submit" fullWidth>
            Set password
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

export function UsersSection() {
  const { data: users, isLoading } = useUsers();
  const createUser = useCreateUser();
  const importUser = useImportUser();
  const setSmbEnabled = useSetUserSmbEnabled();
  const deleteUser = useDeleteUser();
  const setPassword = useSetUserPassword();

  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<UserInfo | null>(null);

  return (
    <div className="nasos-section">
      <div className="nasos-section__toolbar">
        <Group gap="xs">
          <Button
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={() => setCreateOpen(true)}
          >
            Create user
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<IconUserPlus size={14} />}
            onClick={() => setImportOpen(true)}
          >
            Import existing
          </Button>
        </Group>
      </div>

      <Table verticalSpacing="xs" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Username</Table.Th>
            <Table.Th>Description</Table.Th>
            <Table.Th>SMB</Table.Th>
            <Table.Th>Samba password</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!isLoading &&
            users?.map((user) => (
              <Table.Tr key={user.uid}>
                <Table.Td className="nasos-mono">{user.username}</Table.Td>
                <Table.Td>{user.description || "—"}</Table.Td>
                <Table.Td>
                  <Switch
                    size="xs"
                    checked={user.smb_enabled}
                    onChange={(event) =>
                      setSmbEnabled.mutate({
                        uid: user.uid,
                        smbEnabled: event.currentTarget.checked,
                      })
                    }
                  />
                </Table.Td>
                <Table.Td>
                  {user.smb_password_synced ? (
                    <Badge color="green" variant="light" size="sm">
                      synced
                    </Badge>
                  ) : (
                    <Badge color="yellow" variant="light" size="sm">
                      out of sync
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={`Set password for ${user.username}`}
                      onClick={() => setPasswordTarget(user)}
                    >
                      <IconKey size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      color="red"
                      aria-label={`Delete ${user.username}`}
                      onClick={() => deleteUser.mutate({ uid: user.uid, deleteHome: false })}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
        </Table.Tbody>
      </Table>

      <CreateUserModal
        opened={createOpen}
        onClose={() => {
          setCreateOpen(false);
          createUser.reset();
        }}
        error={createUser.error}
        onSubmit={(values) => {
          createUser.mutate(values, { onSuccess: () => setCreateOpen(false) });
        }}
      />
      <ImportUserModal
        opened={importOpen}
        onClose={() => {
          setImportOpen(false);
          importUser.reset();
        }}
        error={importUser.error}
        onSubmit={(values) => {
          importUser.mutate(values, { onSuccess: () => setImportOpen(false) });
        }}
      />
      <SetPasswordModal
        user={passwordTarget}
        onClose={() => {
          setPasswordTarget(null);
          setPassword.reset();
        }}
        error={setPassword.error}
        onSubmit={(password) => {
          if (!passwordTarget) return;
          setPassword.mutate(
            { uid: passwordTarget.uid, password },
            { onSuccess: () => setPasswordTarget(null) },
          );
        }}
      />
    </div>
  );
}
