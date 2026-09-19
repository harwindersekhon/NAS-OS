import { Badge, Button, Group, Table, Text } from "@mantine/core";
import { IconPlus, IconRefresh } from "@tabler/icons-react";
import { useState } from "react";

import type { DiskNode, StorageHealth } from "@/api/storage";
import { useStorageInventory } from "@/api/storage";
import { useVolumes } from "@/api/volumes";
import { ByteSize } from "@/components/ByteSize";

import { CreateVolumeModal } from "./CreateVolumeModal";

const HEALTH_COLOR: Record<StorageHealth, string> = {
  ok: "green",
  warning: "yellow",
  critical: "red",
  unknown: "gray",
};

const HEALTH_LABEL: Record<StorageHealth, string> = {
  ok: "Healthy",
  warning: "Warning",
  critical: "Critical",
  unknown: "Unknown",
};

function HealthBadge({ health }: { health: StorageHealth | undefined }) {
  const value = health ?? "unknown";
  return (
    <Badge color={HEALTH_COLOR[value]} variant="light" size="sm">
      {HEALTH_LABEL[value]}
    </Badge>
  );
}

function DiskRow({ disk }: { disk: DiskNode }) {
  return (
    <Table.Tr>
      <Table.Td className="nasos-mono">{disk.path}</Table.Td>
      <Table.Td>{disk.model ?? "—"}</Table.Td>
      <Table.Td className="nasos-mono">{disk.serial ?? "—"}</Table.Td>
      <Table.Td>
        <ByteSize value={disk.size} />
      </Table.Td>
      <Table.Td className="nasos-mono">{disk.transport}</Table.Td>
      <Table.Td>
        <HealthBadge health={disk.smart?.health} />
        {disk.smart?.temperature_c != null && (
          <Text size="xs" c="dimmed" span ml={6}>
            {disk.smart.temperature_c}°C
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        {disk.protected ? (
          <Badge color="orange" variant="light" size="sm" title={disk.protected_reason ?? undefined}>
            In use
          </Badge>
        ) : (
          <Badge color="gray" variant="outline" size="sm">
            Available
          </Badge>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

export function StorageManager() {
  const { data: inventory, isLoading: inventoryLoading, refetch } = useStorageInventory();
  const { data: volumes, isLoading: volumesLoading } = useVolumes();
  const [createOpen, setCreateOpen] = useState(false);

  const disks = inventory?.disks ?? [];

  return (
    <div className="nasos-storage-manager">
      <div className="nasos-storage-manager__toolbar">
        <Text fw={600} size="sm">
          Volumes
        </Text>
        <Group gap="xs">
          <Button
            size="xs"
            variant="default"
            leftSection={<IconRefresh size={14} />}
            onClick={() => void refetch()}
          >
            Refresh
          </Button>
          <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreateOpen(true)}>
            Create volume
          </Button>
        </Group>
      </div>
      <Table verticalSpacing="xs" mb="lg">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Mountpoint</Table.Th>
            <Table.Th>Filesystem</Table.Th>
            <Table.Th>Type</Table.Th>
            <Table.Th>Managed</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!volumesLoading &&
            volumes?.map((volume) => (
              <Table.Tr key={volume.id}>
                <Table.Td>{volume.name}</Table.Td>
                <Table.Td className="nasos-mono">{volume.mountpoint}</Table.Td>
                <Table.Td className="nasos-mono">{volume.filesystem}</Table.Td>
                <Table.Td>
                  {volume.raid_level
                    ? volume.raid_level === "basic"
                      ? "Basic"
                      : `RAID ${volume.raid_level}`
                    : "—"}
                </Table.Td>
                <Table.Td>
                  {volume.managed ? (
                    <Badge color="blue" variant="light" size="sm" style={{ whiteSpace: "nowrap" }}>
                      Auto-managed
                    </Badge>
                  ) : (
                    <Badge color="gray" variant="outline" size="sm">
                      Manual
                    </Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          {!volumesLoading && volumes?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={5}>
                <Text size="sm" c="dimmed">
                  No volumes yet.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>

      <Text fw={600} size="sm" mb={6}>
        Disks
      </Text>
      <Table verticalSpacing="xs" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Device</Table.Th>
            <Table.Th>Model</Table.Th>
            <Table.Th>Serial</Table.Th>
            <Table.Th>Size</Table.Th>
            <Table.Th>Transport</Table.Th>
            <Table.Th>Health</Table.Th>
            <Table.Th>Status</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {!inventoryLoading && disks.map((disk) => <DiskRow key={disk.path} disk={disk} />)}
          {!inventoryLoading && disks.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={7}>
                <Text size="sm" c="dimmed">
                  No disks found.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>

      <CreateVolumeModal opened={createOpen} onClose={() => setCreateOpen(false)} disks={disks} />
    </div>
  );
}
