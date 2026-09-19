import { useEffect, useRef, useState } from "react";

import { useSystemInfo } from "@/api/system";
import { useTopic } from "@/api/ws";
import { formatBytes } from "@/components/format";

import { Sparkline } from "./Sparkline";

interface MonitorSample {
  cpu_percent: number;
  mem_used: number;
  mem_total: number;
}

const HISTORY_LENGTH = 60;

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function Dashboard() {
  const { data: info } = useSystemInfo();
  const sample = useTopic<MonitorSample>("monitor.sample");

  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [memHistory, setMemHistory] = useState<number[]>([]);
  const lastSample = useRef<MonitorSample | null>(null);

  useEffect(() => {
    if (!sample || sample === lastSample.current) return;
    lastSample.current = sample;
    setCpuHistory((prev) => [...prev.slice(-(HISTORY_LENGTH - 1)), sample.cpu_percent]);
    setMemHistory((prev) => [
      ...prev.slice(-(HISTORY_LENGTH - 1)),
      sample.mem_total > 0 ? (sample.mem_used / sample.mem_total) * 100 : 0,
    ]);
  }, [sample]);

  return (
    <div className="nasos-dashboard">
      <div className="nasos-dashboard__header">
        <div className="nasos-dashboard__hostname">{info?.hostname ?? "—"}</div>
        <div className="nasos-dashboard__subline">
          {info ? `${info.os_pretty_name} · up ${formatUptime(info.uptime_seconds)}` : "Loading…"}
        </div>
      </div>

      <div className="nasos-dashboard__stats">
        <div className="nasos-stat-tile">
          <div className="nasos-stat-tile__header">
            <span className="nasos-stat-tile__label">CPU</span>
            <span className="nasos-stat-tile__value">
              {sample ? `${Math.round(sample.cpu_percent)}%` : "—"}
            </span>
          </div>
          <Sparkline
            data={cpuHistory}
            color="var(--nasos-chart-cpu)"
            max={100}
            formatValue={(v) => `${v.toFixed(0)}%`}
          />
        </div>
        <div className="nasos-stat-tile">
          <div className="nasos-stat-tile__header">
            <span className="nasos-stat-tile__label">Memory</span>
            <span className="nasos-stat-tile__value">
              {sample ? formatBytes(sample.mem_used) : "—"}
            </span>
          </div>
          <Sparkline
            data={memHistory}
            color="var(--nasos-chart-mem)"
            max={100}
            formatValue={(v) => `${v.toFixed(0)}%`}
          />
        </div>
      </div>
    </div>
  );
}
