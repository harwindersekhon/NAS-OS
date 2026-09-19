import { Alert, Breadcrumbs, Button, Modal, Stack, Text, TextInput } from "@mantine/core";
import {
  IconAlertCircle,
  IconFolderPlus,
  IconTrash,
  IconUpload,
  IconX,
  IconZip,
} from "@tabler/icons-react";
import { type ChangeEvent, type FormEvent, useMemo, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import {
  useDelete,
  useFileList,
  useMkdir,
  useMove,
  useRename,
  useRoots,
  useSearch,
  useZip,
} from "@/api/files";
import type { FileEntry } from "@/api/files";
import { useUploadsStore } from "@/stores/uploads";

import { AclEditorDialog } from "./AclEditorDialog";
import { FileGrid } from "./FileGrid";
import { PreviewDialog } from "./PreviewDialog";
import { PropertiesDialog } from "./PropertiesDialog";
import { TreeSidebar } from "./TreeSidebar";
import { UploadTray } from "./UploadTray";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong";
}

function crumbsFor(path: string, roots: { name: string; path: string }[]): { label: string; path: string }[] {
  const root = roots.find((r) => path === r.path || path.startsWith(`${r.path}/`));
  if (!root) return [{ label: path, path }];
  const rest = path.slice(root.path.length).split("/").filter(Boolean);
  const crumbs = [{ label: root.name, path: root.path }];
  let acc = root.path;
  for (const part of rest) {
    acc = `${acc}/${part}`;
    crumbs.push({ label: part, path: acc });
  }
  return crumbs;
}

function CreateFolderModal({
  opened,
  onClose,
  onSubmit,
  error,
}: {
  opened: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
  error: unknown;
}) {
  const [name, setName] = useState("");
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(name);
  };
  return (
    <Modal opened={opened} onClose={onClose} title="New folder">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            autoFocus
            required
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

function RenameModal({
  entry,
  onClose,
  onSubmit,
  error,
}: {
  entry: FileEntry | null;
  onClose: () => void;
  onSubmit: (newName: string) => void;
  error: unknown;
}) {
  const [name, setName] = useState(entry?.name ?? "");
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(name);
  };
  return (
    <Modal opened={entry !== null} onClose={onClose} title={`Rename ${entry?.name ?? ""}`}>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="New name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            autoFocus
            required
          />
          {error !== null && (
            <Alert color="red" icon={<IconAlertCircle size={16} />} variant="light">
              {errorMessage(error)}
            </Alert>
          )}
          <Button type="submit" fullWidth>
            Rename
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

export function FileStation() {
  const { data: roots } = useRoots();
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [createFolderOpen, setCreateFolderOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<FileEntry | null>(null);
  const [propertiesTarget, setPropertiesTarget] = useState<string | null>(null);
  const [aclTarget, setAclTarget] = useState<string | null>(null);
  const [previewTarget, setPreviewTarget] = useState<FileEntry | null>(null);

  const activePath = currentPath ?? (roots && roots.length > 0 ? roots[0].path : null);

  const listing = useFileList(search.trim() === "" ? activePath : null);
  const searchResults = useSearch(activePath, search);
  const entries = search.trim() === "" ? (listing.data?.entries ?? []) : (searchResults.data?.entries ?? []);

  const mkdir = useMkdir(activePath ?? "");
  const rename = useRename(activePath ?? "");
  const delete_ = useDelete(activePath ?? "");
  const move = useMove(activePath ?? "");
  const zip = useZip();
  const startUpload = useUploadsStore((state) => state.startUpload);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const crumbs = useMemo(
    () => (activePath && roots ? crumbsFor(activePath, roots) : []),
    [activePath, roots],
  );

  const navigate = (nextPath: string) => {
    setCurrentPath(nextPath);
    setSelected(new Set());
    setSearch("");
  };

  const handleFilesSelected = (event: ChangeEvent<HTMLInputElement>) => {
    if (!activePath || !event.target.files) return;
    for (const file of Array.from(event.target.files)) startUpload(file, activePath);
    event.target.value = "";
  };

  const handleExternalDrop = (files: File[], destDir: string) => {
    for (const file of files) startUpload(file, destDir);
  };

  const handleMoveInto = (sources: string[], destDir: string) => {
    move.mutate({ sources, dest_dir: destDir });
  };

  const handleZipSelected = () => {
    zip.mutate([...selected]);
  };

  const handleDeleteSelected = () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} item(s)? This cannot be undone.`)) return;
    delete_.mutate([...selected]);
    setSelected(new Set());
  };

  if (!roots) {
    return <div className="nasos-window__loading">Loading…</div>;
  }

  return (
    <div className="nasos-file-station">
      <aside className="nasos-file-station__sidebar">
        <TreeSidebar activePath={activePath} onNavigate={navigate} />
      </aside>
      <div className="nasos-file-station__main">
        <div className="nasos-file-station__toolbar">
          <Breadcrumbs separator="/" className="nasos-file-station__breadcrumbs">
            {crumbs.map((crumb) => (
              <button
                key={crumb.path}
                type="button"
                className="nasos-file-station__crumb"
                onClick={() => navigate(crumb.path)}
              >
                {crumb.label}
              </button>
            ))}
          </Breadcrumbs>
          <div className="nasos-file-station__actions">
            <TextInput
              placeholder="Search this folder"
              size="xs"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              w={180}
            />
            <Button
              size="xs"
              variant="default"
              leftSection={<IconFolderPlus size={14} />}
              onClick={() => setCreateFolderOpen(true)}
              disabled={!activePath}
            >
              New folder
            </Button>
            <Button
              size="xs"
              leftSection={<IconUpload size={14} />}
              onClick={() => fileInputRef.current?.click()}
              disabled={!activePath}
            >
              Upload
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={handleFilesSelected}
              aria-label="Choose files to upload"
            />
            {selected.size > 0 && (
              <>
                <Button size="xs" variant="default" leftSection={<IconZip size={14} />} onClick={handleZipSelected}>
                  Zip ({selected.size})
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  color="red"
                  leftSection={<IconTrash size={14} />}
                  onClick={handleDeleteSelected}
                >
                  Delete ({selected.size})
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<IconX size={14} />}
                  onClick={() => setSelected(new Set())}
                >
                  Clear
                </Button>
              </>
            )}
          </div>
        </div>

        {roots.length === 0 ? (
          <div className="nasos-file-station__empty-state">
            <Text size="sm" c="dimmed">
              No shared folders yet. Create one from Control Panel → Shared Folders.
            </Text>
          </div>
        ) : (
          <FileGrid
            entries={entries}
            currentPath={activePath ?? ""}
            selected={selected}
            onSelectionChange={setSelected}
            onNavigate={navigate}
            onPreview={setPreviewTarget}
            onMoveInto={handleMoveInto}
            onRename={setRenameTarget}
            onDelete={(paths) => {
              if (!window.confirm(`Delete ${paths.length} item(s)? This cannot be undone.`)) return;
              delete_.mutate(paths);
            }}
            onProperties={setPropertiesTarget}
            onAcl={setAclTarget}
            onExternalDrop={handleExternalDrop}
          />
        )}

        <UploadTray />
      </div>

      <CreateFolderModal
        opened={createFolderOpen}
        onClose={() => {
          setCreateFolderOpen(false);
          mkdir.reset();
        }}
        error={mkdir.error}
        onSubmit={(name) => mkdir.mutate(name, { onSuccess: () => setCreateFolderOpen(false) })}
      />
      <RenameModal
        entry={renameTarget}
        onClose={() => {
          setRenameTarget(null);
          rename.reset();
        }}
        error={rename.error}
        onSubmit={(newName) => {
          if (!renameTarget) return;
          rename.mutate(
            { path: renameTarget.path, new_name: newName },
            { onSuccess: () => setRenameTarget(null) },
          );
        }}
      />
      <PropertiesDialog path={propertiesTarget} onClose={() => setPropertiesTarget(null)} />
      <AclEditorDialog path={aclTarget} onClose={() => setAclTarget(null)} />
      <PreviewDialog entry={previewTarget} onClose={() => setPreviewTarget(null)} />
    </div>
  );
}
