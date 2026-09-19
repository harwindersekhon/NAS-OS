import { useSystemInfo } from "@/api/system";

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [
    days > 0 ? `${days}d` : null,
    hours > 0 ? `${hours}h` : null,
    `${minutes}m`,
  ].filter(Boolean);
  return parts.join(" ");
}

export function InfoSection() {
  const { data: info, isLoading } = useSystemInfo();

  if (isLoading || !info) {
    return <div className="nasos-info-center nasos-info-center--loading">Loading…</div>;
  }

  const rows: Array<[string, string]> = [
    ["Hostname", info.hostname],
    ["Operating system", info.os_pretty_name],
    ["Kernel", info.kernel],
    ["NAS-OS version", info.nasos_version],
    ["Uptime", formatUptime(info.uptime_seconds)],
  ];

  return (
    <div className="nasos-info-center">
      <dl className="nasos-info-center__list">
        {rows.map(([label, value]) => (
          <div className="nasos-info-center__row" key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
