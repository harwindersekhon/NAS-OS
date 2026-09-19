import { IconMinus, IconSquare, IconSquareOff, IconX } from "@tabler/icons-react";
import { Suspense, useCallback, useRef } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";

import type { AppManifest } from "@/apps/registry";

import { useWmStore } from "./store";
import type { WindowInstance } from "./store";

interface DragOrigin {
  pointerX: number;
  pointerY: number;
  x: number;
  y: number;
}

interface ResizeOrigin {
  pointerX: number;
  pointerY: number;
  w: number;
  h: number;
}

interface WindowProps {
  win: WindowInstance;
  manifest: AppManifest;
  isFocused: boolean;
}

export function Window({ win, manifest, isFocused }: WindowProps) {
  const move = useWmStore((s) => s.move);
  const resize = useWmStore((s) => s.resize);
  const focus = useWmStore((s) => s.focus);
  const close = useWmStore((s) => s.close);
  const minimize = useWmStore((s) => s.minimize);
  const toggleMaximize = useWmStore((s) => s.toggleMaximize);

  const dragOrigin = useRef<DragOrigin | null>(null);
  const resizeOrigin = useRef<ResizeOrigin | null>(null);

  const isMaximized = win.state === "maximized";

  const handleTitlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (isMaximized || event.button !== 0) return;
      dragOrigin.current = {
        pointerX: event.clientX,
        pointerY: event.clientY,
        x: win.geometry.x,
        y: win.geometry.y,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [isMaximized, win.geometry.x, win.geometry.y],
  );

  const handleTitlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const origin = dragOrigin.current;
      if (!origin) return;
      const dx = event.clientX - origin.pointerX;
      const dy = event.clientY - origin.pointerY;
      move(win.id, Math.max(0, origin.x + dx), Math.max(0, origin.y + dy));
    },
    [move, win.id],
  );

  const endDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const handleResizePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      resizeOrigin.current = {
        pointerX: event.clientX,
        pointerY: event.clientY,
        w: win.geometry.w,
        h: win.geometry.h,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [win.geometry.w, win.geometry.h],
  );

  const handleResizePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const origin = resizeOrigin.current;
      if (!origin) return;
      const dx = event.clientX - origin.pointerX;
      const dy = event.clientY - origin.pointerY;
      resize(
        win.id,
        Math.max(manifest.minSize.w, origin.w + dx),
        Math.max(manifest.minSize.h, origin.h + dy),
      );
    },
    [resize, win.id, manifest.minSize.w, manifest.minSize.h],
  );

  const endResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    resizeOrigin.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  if (win.state === "minimized") return null;

  // "100%" here fills .nasos-desktop, which is already sized below the
  // taskbar by the shell's flex layout (App.tsx) — no offset needed.
  const style: CSSProperties = isMaximized
    ? { left: 0, top: 0, width: "100%", height: "100%", zIndex: win.z }
    : {
        left: win.geometry.x,
        top: win.geometry.y,
        width: win.geometry.w,
        height: win.geometry.h,
        zIndex: win.z,
      };

  const Component = manifest.component;

  return (
    <div
      className={`nasos-window${isFocused ? " nasos-window--focused" : ""}`}
      style={style}
      onPointerDownCapture={() => focus(win.id)}
      role="dialog"
      aria-label={win.title}
    >
      <div
        className="nasos-window__titlebar"
        onPointerDown={handleTitlePointerDown}
        onPointerMove={handleTitlePointerMove}
        onPointerUp={endDrag}
        onDoubleClick={() => toggleMaximize(win.id)}
      >
        <span className="nasos-window__title">{win.title}</span>
        <div className="nasos-window__controls">
          <button
            type="button"
            className="nasos-window__control"
            aria-label="Minimize"
            onClick={() => minimize(win.id)}
          >
            <IconMinus size={14} stroke={1.75} />
          </button>
          <button
            type="button"
            className="nasos-window__control"
            aria-label={isMaximized ? "Restore" : "Maximize"}
            onClick={() => toggleMaximize(win.id)}
          >
            {isMaximized ? (
              <IconSquareOff size={13} stroke={1.75} />
            ) : (
              <IconSquare size={12} stroke={1.75} />
            )}
          </button>
          <button
            type="button"
            className="nasos-window__control nasos-window__control--close"
            aria-label="Close"
            onClick={() => close(win.id)}
          >
            <IconX size={14} stroke={1.75} />
          </button>
        </div>
      </div>
      <div className="nasos-window__body">
        <Suspense fallback={<div className="nasos-window__loading">Loading…</div>}>
          <Component />
        </Suspense>
      </div>
      {!isMaximized && (
        <div
          className="nasos-window__resize-handle"
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={endResize}
        />
      )}
    </div>
  );
}
