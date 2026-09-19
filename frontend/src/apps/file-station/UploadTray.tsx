import { ActionIcon, Progress, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";

import { formatBytes } from "@/components/format";
import { useUploadsStore } from "@/stores/uploads";

export function UploadTray() {
  const uploads = useUploadsStore((state) => state.uploads);
  const dismiss = useUploadsStore((state) => state.dismiss);
  const items = Object.values(uploads).sort((a, b) => (a.id < b.id ? 1 : -1));

  if (items.length === 0) return null;

  return (
    <div className="nasos-upload-tray">
      {items.map((upload) => {
        const percent =
          upload.bytesTotal > 0 ? Math.round((upload.bytesSent / upload.bytesTotal) * 100) : 0;
        return (
          <div key={upload.id} className="nasos-upload-tray__item">
            <div className="nasos-upload-tray__row">
              <Text size="xs" fw={500} truncate style={{ flex: 1 }}>
                {upload.filename}
              </Text>
              {upload.status === "uploading" && (
                <Text size="xs" c="dimmed" className="nasos-mono">
                  {formatBytes(upload.bytesSent)} / {formatBytes(upload.bytesTotal)}
                </Text>
              )}
              {upload.status === "done" && <IconCheck size={14} color="var(--nasos-status-good)" />}
              {upload.status === "error" && <IconX size={14} color="var(--nasos-status-critical)" />}
              {upload.status !== "uploading" && (
                <ActionIcon
                  variant="subtle"
                  size="xs"
                  aria-label={`Dismiss ${upload.filename}`}
                  onClick={() => dismiss(upload.id)}
                >
                  <IconX size={12} />
                </ActionIcon>
              )}
              {upload.status === "uploading" && (
                <ActionIcon
                  variant="subtle"
                  size="xs"
                  color="red"
                  aria-label={`Cancel ${upload.filename}`}
                  onClick={() => {
                    upload.abort();
                    dismiss(upload.id);
                  }}
                >
                  <IconX size={12} />
                </ActionIcon>
              )}
            </div>
            {upload.status === "uploading" && <Progress value={percent} size="xs" />}
            {upload.status === "error" && (
              <Text size="xs" c="red">
                {upload.error}
              </Text>
            )}
          </div>
        );
      })}
    </div>
  );
}
