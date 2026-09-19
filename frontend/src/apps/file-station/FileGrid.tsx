import { ActionIcon, Menu } from "@mantine/core";
import {
  IconDots,
  IconDownload,
  IconFile,
  IconFolder,
  IconLock,
  IconPencil,
  IconTrash,
} from "@tabler/icons-react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { SortingState } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { type DragEvent, type MouseEvent as ReactMouseEvent, useRef, useState } from "react";

import type { FileEntry } from "@/api/files";
import { contentUrl } from "@/api/files";
import { formatBytes } from "@/components/format";

const DRAG_MIME = "application/x-nasos-paths";

function formatDate(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

interface FileGridProps {
  entries: FileEntry[];
  currentPath: string;
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  onNavigate: (path: string) => void;
  onPreview: (entry: FileEntry) => void;
  onMoveInto: (sources: string[], destDir: string) => void;
  onRename: (entry: FileEntry) => void;
  onDelete: (paths: string[]) => void;
  onProperties: (path: string) => void;
  onAcl: (path: string) => void;
  onExternalDrop: (files: File[], destDir: string) => void;
}

const columnHelper = createColumnHelper<FileEntry>();

export function FileGrid({
  entries,
  currentPath,
  selected,
  onSelectionChange,
  onNavigate,
  onPreview,
  onMoveInto,
  onRename,
  onDelete,
  onProperties,
  onAcl,
  onExternalDrop,
}: FileGridProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [dragOverPath, setDragOverPath] = useState<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);
  const lastClickedRef = useRef<string | null>(null);

  const columns = [
    columnHelper.accessor("name", {
      header: "Name",
      cell: (info) => (
        <span className="nasos-file-grid__name">
          {info.row.original.is_dir ? (
            <IconFolder size={16} stroke={1.75} />
          ) : (
            <IconFile size={16} stroke={1.75} />
          )}
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor("size", {
      header: "Size",
      cell: (info) => (info.row.original.is_dir ? "—" : formatBytes(info.getValue())),
    }),
    columnHelper.accessor("mtime", {
      header: "Modified",
      cell: (info) => formatDate(info.getValue()),
    }),
  ];

  // React Compiler can't safely memoize TanStack Table's returned object
  // (it hands back fresh functions every render by design) and correctly
  // bails out for this hook — expected, not a bug; FileGrid re-renders on
  // every entries/sorting change regardless, same as pre-compiler React.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: entries,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const rows = table.getRowModel().rows;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 34,
    overscan: 12,
  });

  const handleRowClick = (event: ReactMouseEvent, entry: FileEntry) => {
    const next = new Set(selected);
    if (event.shiftKey && lastClickedRef.current) {
      const paths = entries.map((e) => e.path);
      const start = paths.indexOf(lastClickedRef.current);
      const end = paths.indexOf(entry.path);
      const [lo, hi] = start < end ? [start, end] : [end, start];
      for (const p of paths.slice(lo, hi + 1)) next.add(p);
    } else if (event.metaKey || event.ctrlKey) {
      if (next.has(entry.path)) next.delete(entry.path);
      else next.add(entry.path);
    } else {
      next.clear();
      next.add(entry.path);
    }
    lastClickedRef.current = entry.path;
    onSelectionChange(next);
  };

  const handleDragStart = (event: DragEvent, entry: FileEntry) => {
    const paths = selected.has(entry.path) ? [...selected] : [entry.path];
    event.dataTransfer.setData(DRAG_MIME, JSON.stringify(paths));
    event.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (event: DragEvent, targetPath: string | null) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes(DRAG_MIME)
      ? "move"
      : "copy";
    setDragOverPath(targetPath);
  };

  const handleDrop = (event: DragEvent, destDir: string) => {
    event.preventDefault();
    setDragOverPath(null);
    const internal = event.dataTransfer.getData(DRAG_MIME);
    if (internal) {
      const sources = JSON.parse(internal) as string[];
      if (!sources.includes(destDir)) onMoveInto(sources, destDir);
      return;
    }
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onExternalDrop(files, destDir);
  };

  return (
    <div
      ref={parentRef}
      className={`nasos-file-grid${dragOverPath === currentPath ? " nasos-file-grid--drop-target" : ""}`}
      onDragOver={(e) => handleDragOver(e, currentPath)}
      onDragLeave={() => setDragOverPath(null)}
      onDrop={(e) => handleDrop(e, currentPath)}
    >
      <div className="nasos-file-grid__header">
        {table.getHeaderGroups().map((headerGroup) =>
          headerGroup.headers.map((header) => (
            <button
              key={header.id}
              type="button"
              className={`nasos-file-grid__header-cell nasos-file-grid__col--${header.column.id}`}
              onClick={header.column.getToggleSortingHandler()}
            >
              {flexRender(header.column.columnDef.header, header.getContext())}
              {{ asc: " ▲", desc: " ▼" }[header.column.getIsSorted() as string] ?? ""}
            </button>
          )),
        )}
        <span className="nasos-file-grid__header-cell nasos-file-grid__col--actions" />
      </div>
      {entries.length === 0 && <p className="nasos-file-grid__empty">This folder is empty.</p>}
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const row = rows[virtualRow.index];
          const entry = row.original;
          const isDropTarget = entry.is_dir && dragOverPath === entry.path;
          return (
            <div
              key={row.id}
              className={`nasos-file-grid__row${selected.has(entry.path) ? " nasos-file-grid__row--selected" : ""}${isDropTarget ? " nasos-file-grid__row--drop-target" : ""}`}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                height: virtualRow.size,
                transform: `translateY(${virtualRow.start}px)`,
              }}
              onDragStart={(e) => handleDragStart(e, entry)}
              onDragOver={(e) => {
                if (entry.is_dir) {
                  e.stopPropagation();
                  handleDragOver(e, entry.path);
                }
              }}
              onDrop={(e) => {
                if (entry.is_dir) {
                  e.stopPropagation();
                  handleDrop(e, entry.path);
                }
              }}
              onClick={(e) => handleRowClick(e, entry)}
              onDoubleClick={() => (entry.is_dir ? onNavigate(entry.path) : onPreview(entry))}
            >
              {row.getVisibleCells().map((cell) => (
                <span key={cell.id} className={`nasos-file-grid__cell nasos-file-grid__col--${cell.column.id}`}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </span>
              ))}
              <span className="nasos-file-grid__cell nasos-file-grid__col--actions">
                <Menu position="bottom-end" withinPortal>
                  <Menu.Target>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={`Actions for ${entry.name}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <IconDots size={14} />
                    </ActionIcon>
                  </Menu.Target>
                  <Menu.Dropdown>
                    {!entry.is_dir && (
                      <Menu.Item
                        leftSection={<IconDownload size={14} />}
                        component="a"
                        href={contentUrl(entry.path, "attachment")}
                      >
                        Download
                      </Menu.Item>
                    )}
                    <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => onRename(entry)}>
                      Rename
                    </Menu.Item>
                    <Menu.Item leftSection={<IconLock size={14} />} onClick={() => onAcl(entry.path)}>
                      Permissions
                    </Menu.Item>
                    <Menu.Item onClick={() => onProperties(entry.path)}>Properties</Menu.Item>
                    <Menu.Item
                      color="red"
                      leftSection={<IconTrash size={14} />}
                      onClick={() => onDelete([entry.path])}
                    >
                      Delete
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
