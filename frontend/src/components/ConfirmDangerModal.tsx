import { Alert, Button, Modal, Stack, Text, TextInput } from "@mantine/core";
import { IconAlertCircle, IconAlertTriangle } from "@tabler/icons-react";
import { type ReactNode, useState } from "react";

import { ApiError } from "@/api/client";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

/**
 * A destructive action gated on the user typing an exact phrase back
 * (PLAN.md §6: "user types the disk serial or ERASE") rather than a plain
 * confirm button — used wherever a mistake can't be undone by clicking
 * "cancel" a second later.
 */
export function ConfirmDangerModal({
  opened,
  onClose,
  title,
  description,
  confirmText,
  confirmLabel = "Confirm",
  onConfirm,
  loading = false,
  error = null,
}: {
  opened: boolean;
  onClose: () => void;
  title: string;
  description: ReactNode;
  confirmText: string;
  confirmLabel?: string;
  onConfirm: () => void;
  loading?: boolean;
  error?: unknown;
}) {
  const [typed, setTyped] = useState("");

  return (
    <Modal
      opened={opened}
      onClose={() => {
        setTyped("");
        onClose();
      }}
      title={title}
      size="md"
    >
      <Stack gap="sm">
        {description}
        <Alert color="red" icon={<IconAlertTriangle size={16} />} variant="light">
          This cannot be undone.
        </Alert>
        <TextInput
          label={
            <>
              Type <span className="nasos-mono">{confirmText}</span> to confirm
            </>
          }
          value={typed}
          onChange={(event) => setTyped(event.currentTarget.value)}
          autoFocus
        />
        {error !== null && (
          <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
            {errorMessage(error)}
          </Alert>
        )}
        <Button
          color="red"
          fullWidth
          disabled={typed !== confirmText}
          loading={loading}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
        <Text size="xs" c="dimmed" ta="center">
          Case-sensitive, must match exactly.
        </Text>
      </Stack>
    </Modal>
  );
}
