import { useMemo, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

interface SparklinePoint {
  x: number;
  y: number;
  value: number;
}

interface SparklineProps {
  data: number[];
  color: string;
  max: number;
  formatValue: (value: number) => string;
  width?: number;
  height?: number;
}

const PADDING = 4;

export function Sparkline({
  data,
  color,
  max,
  formatValue,
  width = 240,
  height = 64,
}: SparklineProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const points = useMemo<SparklinePoint[]>(() => {
    if (data.length === 0) return [];
    const innerW = width - PADDING * 2;
    const innerH = height - PADDING * 2;
    const step = data.length > 1 ? innerW / (data.length - 1) : 0;
    return data.map((value, i) => {
      const clamped = Math.max(0, Math.min(max, value));
      return {
        x: PADDING + i * step,
        y: PADDING + innerH - (clamped / max) * innerH,
        value,
      };
    });
  }, [data, max, width, height]);

  if (points.length < 2) {
    return <svg width={width} height={height} className="nasos-sparkline" aria-hidden="true" />;
  }

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");
  const baseline = height - PADDING;
  const areaPath = `${linePath} L${points[points.length - 1].x.toFixed(1)},${baseline} L${points[0].x.toFixed(1)},${baseline} Z`;
  const last = points[points.length - 1];
  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  const handleMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * width;
    const innerW = width - PADDING * 2;
    const step = innerW / (points.length - 1);
    const index = Math.round((relX - PADDING) / step);
    setHoverIndex(Math.max(0, Math.min(points.length - 1, index)));
  };

  const tooltipX = Math.min(width - 66, Math.max(0, (hovered?.x ?? 0) - 28));

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="nasos-sparkline"
      onPointerMove={handleMove}
      onPointerLeave={() => setHoverIndex(null)}
      role="img"
    >
      <path d={areaPath} fill={color} fillOpacity={0.12} stroke="none" />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={last.x} cy={last.y} r={3} fill={color} />
      {hovered && (
        <>
          <line
            x1={hovered.x}
            y1={PADDING}
            x2={hovered.x}
            y2={baseline}
            className="nasos-sparkline__crosshair"
          />
          <circle
            cx={hovered.x}
            cy={hovered.y}
            r={3.5}
            fill={color}
            stroke="var(--nasos-surface)"
            strokeWidth={1.5}
          />
          <foreignObject x={tooltipX} y={0} width={66} height={18}>
            <div className="nasos-sparkline__tooltip">{formatValue(hovered.value)}</div>
          </foreignObject>
        </>
      )}
    </svg>
  );
}
