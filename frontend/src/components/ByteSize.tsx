import { formatBytes } from "./format";

export function ByteSize({ value }: { value: number }) {
  return <span className="nasos-mono">{formatBytes(value)}</span>;
}
