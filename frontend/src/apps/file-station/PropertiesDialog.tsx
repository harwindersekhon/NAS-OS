import { Modal, Text } from "@mantine/core";

import { useProperties } from "@/api/files";
import { formatBytes } from "@/components/format";

export function PropertiesDialog({ path, onClose }: { path: string | null; onClose: () => void }) {
  const { data, isLoading } = useProperties(path);

  return (
    <Modal opened={path !== null} onClose={onClose} title="Properties" size="sm">
      {!isLoading && data ? (
        <dl className="nasos-properties">
          <div className="nasos-properties__row">
            <dt>Name</dt>
            <dd>{data.name}</dd>
          </div>
          <div className="nasos-properties__row">
            <dt>Location</dt>
            <dd className="nasos-mono">{data.path}</dd>
          </div>
          <div className="nasos-properties__row">
            <dt>Type</dt>
            <dd>{data.is_dir ? "Folder" : "File"}</dd>
          </div>
          <div className="nasos-properties__row">
            <dt>Size</dt>
            <dd>{formatBytes(data.size)}</dd>
          </div>
          {data.item_count !== null && (
            <div className="nasos-properties__row">
              <dt>Items</dt>
              <dd>{data.item_count}</dd>
            </div>
          )}
          <div className="nasos-properties__row">
            <dt>Modified</dt>
            <dd>{new Date(data.mtime * 1000).toLocaleString()}</dd>
          </div>
          <div className="nasos-properties__row">
            <dt>Owner</dt>
            <dd>{data.owner_name}</dd>
          </div>
          <div className="nasos-properties__row">
            <dt>Mode</dt>
            <dd className="nasos-mono">{data.mode}</dd>
          </div>
        </dl>
      ) : (
        <Text size="sm" c="dimmed">
          Loading…
        </Text>
      )}
    </Modal>
  );
}
