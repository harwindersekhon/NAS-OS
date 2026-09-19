import { IconChevronRight, IconFolder } from "@tabler/icons-react";
import { useState } from "react";

import { useFileList, useRoots } from "@/api/files";
import type { FileEntry } from "@/api/files";

function TreeNode({
  path,
  name,
  depth,
  activePath,
  onNavigate,
}: {
  path: string;
  name: string;
  depth: number;
  activePath: string | null;
  onNavigate: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data } = useFileList(expanded ? path : null);
  const dirs = (data?.entries ?? []).filter((e: FileEntry) => e.is_dir);

  return (
    <div>
      <div
        className={`nasos-file-tree__row${activePath === path ? " nasos-file-tree__row--active" : ""}`}
        style={{ paddingLeft: 10 + depth * 16 }}
      >
        <button
          type="button"
          className="nasos-file-tree__chevron"
          aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
        >
          <IconChevronRight
            size={13}
            style={{ transform: expanded ? "rotate(90deg)" : undefined }}
          />
        </button>
        <button type="button" className="nasos-file-tree__label" onClick={() => onNavigate(path)}>
          <IconFolder size={15} stroke={1.75} />
          <span>{name}</span>
        </button>
      </div>
      {expanded &&
        dirs.map((dir: FileEntry) => (
          <TreeNode
            key={dir.path}
            path={dir.path}
            name={dir.name}
            depth={depth + 1}
            activePath={activePath}
            onNavigate={onNavigate}
          />
        ))}
    </div>
  );
}

export function TreeSidebar({
  activePath,
  onNavigate,
}: {
  activePath: string | null;
  onNavigate: (path: string) => void;
}) {
  const { data: roots, isLoading } = useRoots();

  return (
    <nav className="nasos-file-tree">
      {!isLoading && roots?.length === 0 && (
        <p className="nasos-file-tree__empty">No shared folders yet.</p>
      )}
      {roots?.map((root) => (
        <TreeNode
          key={root.id}
          path={root.path}
          name={root.name}
          depth={0}
          activePath={activePath}
          onNavigate={onNavigate}
        />
      ))}
    </nav>
  );
}
