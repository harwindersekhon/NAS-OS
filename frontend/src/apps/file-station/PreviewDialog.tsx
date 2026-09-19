import { Button, Modal, Text } from "@mantine/core";
import { useEffect, useState } from "react";

import type { FileEntry } from "@/api/files";
import { contentUrl } from "@/api/files";

const TEXT_PREVIEW_LIMIT = 2 * 1024 * 1024; // PLAN.md §5: text preview up to 2 MiB

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"]);
const VIDEO_EXT = new Set(["mp4", "webm", "ogv", "mov"]);
const AUDIO_EXT = new Set(["mp3", "wav", "ogg", "flac", "m4a"]);
const TEXT_EXT = new Set([
  "txt",
  "md",
  "json",
  "yaml",
  "yml",
  "toml",
  "conf",
  "log",
  "csv",
  "ini",
  "py",
  "js",
  "ts",
  "tsx",
  "jsx",
  "sh",
  "css",
  "html",
  "xml",
]);

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function TextPreview({ path, size }: { path: string; size: number }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (size > TEXT_PREVIEW_LIMIT) return;
    fetch(contentUrl(path))
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error("failed"))))
      .then(setText)
      .catch(() => setError(true));
  }, [path, size]);

  if (size > TEXT_PREVIEW_LIMIT) {
    return (
      <Text size="sm" c="dimmed">
        This file is larger than 2 MiB — too large to preview as text.
      </Text>
    );
  }
  if (error) {
    return (
      <Text size="sm" c="dimmed">
        Couldn't load a preview for this file.
      </Text>
    );
  }
  if (text === null) {
    return (
      <Text size="sm" c="dimmed">
        Loading…
      </Text>
    );
  }
  return <pre className="nasos-file-preview__text">{text}</pre>;
}

export function PreviewDialog({
  entry,
  onClose,
}: {
  entry: FileEntry | null;
  onClose: () => void;
}) {
  if (!entry) {
    return <Modal opened={false} onClose={onClose} title="" />;
  }

  const ext = extensionOf(entry.name);
  const url = contentUrl(entry.path);

  let body: React.ReactNode;
  if (IMAGE_EXT.has(ext)) {
    body = <img src={url} alt={entry.name} className="nasos-file-preview__image" />;
  } else if (VIDEO_EXT.has(ext)) {
    body = (
      <video src={url} controls className="nasos-file-preview__media">
        <track kind="captions" />
      </video>
    );
  } else if (AUDIO_EXT.has(ext)) {
    body = (
      <audio src={url} controls className="nasos-file-preview__audio">
        <track kind="captions" />
      </audio>
    );
  } else if (ext === "pdf") {
    body = <iframe src={url} title={entry.name} className="nasos-file-preview__pdf" />;
  } else if (TEXT_EXT.has(ext)) {
    body = <TextPreview key={entry.path} path={entry.path} size={entry.size} />;
  } else {
    body = (
      <Text size="sm" c="dimmed">
        No preview available for this file type.
      </Text>
    );
  }

  return (
    <Modal opened onClose={onClose} title={entry.name} size="lg">
      {body}
      <Button
        component="a"
        href={contentUrl(entry.path, "attachment")}
        variant="default"
        size="xs"
        mt="md"
      >
        Download
      </Button>
    </Modal>
  );
}
