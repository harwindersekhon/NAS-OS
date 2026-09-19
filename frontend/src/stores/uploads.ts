import * as tus from "tus-js-client";
import { create } from "zustand";

// 16 MiB tus PATCH chunks (PLAN.md §5) — an internal, independent detail
// from the fileworker's own 1 MiB binary-frame size (PLAN.md §1): the
// server re-chunks whatever the client sends into 1 MiB pieces itself, so
// nothing here needs to match that number.
const CHUNK_SIZE = 16 * 1024 * 1024;

export type UploadStatus = "uploading" | "done" | "error";

export interface UploadState {
  id: string;
  filename: string;
  destDir: string;
  bytesSent: number;
  bytesTotal: number;
  status: UploadStatus;
  error: string | null;
  abort: () => void;
}

interface UploadsStore {
  uploads: Record<string, UploadState>;
  /** Starts (or resumes, if a matching previous attempt is found in
   * localStorage — tus-js-client's own resumability, PLAN.md §5) a tus
   * upload of `file` into `destDir`. */
  startUpload: (file: File, destDir: string) => void;
  dismiss: (id: string) => void;
}

let nextId = 0;

export const useUploadsStore = create<UploadsStore>((set) => ({
  uploads: {},

  startUpload: (file, destDir) => {
    const id = `${Date.now()}-${nextId++}`;
    const upsert = (patch: Partial<UploadState>) =>
      set((state) => ({
        uploads: { ...state.uploads, [id]: { ...state.uploads[id], ...patch } },
      }));

    const upload = new tus.Upload(file, {
      endpoint: "/api/v1/uploads",
      chunkSize: CHUNK_SIZE,
      headers: { "X-NASOS-Request": "1" },
      metadata: { filename: file.name, dir: destDir },
      storeFingerprintForResuming: true,
      removeFingerprintOnSuccess: true,
      onProgress: (bytesSent, bytesTotal) => upsert({ bytesSent, bytesTotal }),
      onSuccess: () => upsert({ status: "done", bytesSent: file.size }),
      onError: (error) =>
        upsert({ status: "error", error: error instanceof Error ? error.message : String(error) }),
    });

    upsert({
      id,
      filename: file.name,
      destDir,
      bytesSent: 0,
      bytesTotal: file.size,
      status: "uploading",
      error: null,
      abort: () => {
        void upload.abort();
      },
    });

    void upload.findPreviousUploads().then((previousUploads) => {
      if (previousUploads.length > 0) {
        upload.resumeFromPreviousUpload(previousUploads[0]);
      }
      upload.start();
    });
  },

  dismiss: (id) =>
    set((state) => {
      const uploads = { ...state.uploads };
      delete uploads[id];
      return { uploads };
    }),
}));
