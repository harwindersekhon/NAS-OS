# NAS-OS

A DSM-style NAS management system for Linux. Installs on an existing
RHEL-family server (Rocky/Alma/RHEL 10, Fedora) and provides a browser-based,
desktop-style GUI to manage shared folders, users/groups and permissions,
SMB (Samba), NFS, FTP (vsftpd), storage (disks/RAID/LVM), resource
monitoring, scheduled tasks and rsync backups, and network/firewall
settings.

Backend is Python/FastAPI with a privilege-separated root agent (all
system-level changes — users, Samba config, disk/RAID operations — go
through a small RPC surface, never directly from the web process). Frontend
is a React/TypeScript desktop shell (custom window manager, taskbar,
launcher) built with Vite and Mantine.

See [PLAN.md](PLAN.md) for the full architecture and implementation plan.

## Status

Under active development, built as 8 sequential milestones (PLAN.md §12);
each milestone's gate must pass before the next starts.

- [x] **M1 — Skeleton**: sessions/RBAC/CSRF, audit log, desktop shell (window
      manager, taskbar, launcher), live Dashboard, dev mode with fake system
      adapters, RPM packaging skeleton.
- [x] **M2 — Users, groups, shares, SMB**: user/group CRUD with password
      sync, shared folders + ACL model, Samba config rendering + reload,
      firewalld integration, notifications.
- [x] **M3 — File Station**: per-user fileworker process, tus 1.0 resumable
      uploads, browse/search/sort, copy/move/delete/zip as background jobs,
      ACL editor, previews.
- [x] **M4 — Storage Manager**: disk/SMART inventory, the protected-device
      guard, two-phase plan/execute with a typed confirmation, md/LVM/mkfs
      orchestration, systemd mount units, auto volume registration, SMART
      health notifications.
- [ ] **M5 — NFS, FTP, Network, Firewall, Discovery**
- [ ] **M6 — Resource Monitor + Log Center**
- [ ] **M7 — Task Scheduler + rsync backup**
- [ ] **M8 — Hardening + release**

## Development

```
make bootstrap   # create backend venv, install frontend deps
make dev         # run backend (dev mode, fakes) + frontend dev server
make test        # backend + frontend unit tests
make lint        # ruff, mypy, eslint, tsc
```

`make dev` runs the backend against fake system adapters (`NASOS_MODE=dev`)
so it needs no root privileges and never touches real system state — see
PLAN.md §10 for the full dev workflow, including running against a real
(unprivileged-socket) dev agent and loop-device storage testing.

Once both dev servers are up, open http://127.0.0.1:5173/ and sign in with
one of the seeded dev accounts in `backend/devdata/devusers.toml`
(`admin` / `adminpass123` by default).

## License

MIT — see [LICENSE](LICENSE).
