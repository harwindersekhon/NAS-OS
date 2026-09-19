# NAS-OS: DSM-style NAS management for Linux — Architecture & Implementation Plan

## Context

Goal: build an open-source, Synology DiskStation Manager (DSM)-like NAS management system that installs on an existing Linux server (RHEL family first) and provides a browser-based, desktop-style GUI to manage shared folders, users/groups and permissions, SMB (Samba), NFS, FTP (vsftpd), storage (disks/RAID/LVM), resource monitoring, scheduled tasks and rsync backups, and network/firewall settings. Not every DSM feature is needed; the target is a coherent, safe subset a home/small-office admin can run on a stock Rocky/Alma/RHEL box.

`/home/harwinder/Development/NAS-OS` is empty (greenfield, not yet a git repo).

### Decisions made with the user

| Decision | Choice |
|---|---|
| GUI | Web app with a DSM-style desktop shell (draggable windows, taskbar, launcher) |
| Stack | Python 3.12 + FastAPI backend; React + TypeScript + Vite frontend (Node only for building) |
| Target OS v1 | RHEL family (Rocky/Alma/RHEL 10, Fedora); RPM + systemd; distro-adapter layer so Debian can follow |
| v1 scope | Core (users/groups, shared folders + permissions, SMB, NFS, FTP, File Station, dashboard) **plus** Storage Manager, Resource Monitor, Task Scheduler + rsync backups, Network & Firewall |
| Cadence | Build all 8 milestones sequentially without pausing; each milestone's verification gate must pass before the next starts |
| License | MIT |

### Verified environment facts (dev box = representative target)

- Rocky Linux 10.2, kernel 6.12, systemd 257, **SELinux enforcing**, firewalld, NetworkManager, polkit 125.
- Python 3.12.14. System packages present: `sqlalchemy` 2.0, `dbus-python`, `dasbus` 1.7, `blivet` 3.13, PyGObject, `python3-firewall`, `python3-inotify`, `python3-pyudev` 0.24, `python3-pam` 2.0.
- Installed tools: nfs-utils (`exportfs`, `rpc.nfsd`), mdadm 4.4, lvm2, smartmontools, udisks2, parted 3.6 (`-j` JSON), acl, shadow-utils, firewall-cmd/nft, rsync 3.4, nmcli 1.56, avahi-daemon, wsdd (`BindsTo=smb.service`). Cockpit is installed (prior art only).
- **Not installed, in repos**: `samba` 4.23 (baseos), `vsftpd` 3.0.5 (appstream), `nodejs` 22 (appstream). Python deps in repos: `python3-fastapi` 0.115, `python3-uvicorn` 0.35, `python3-pydantic` 2.9, `python3-psutil`, `python3-aiofiles`, `python3-jinja2`, `python3-websockets` (mix of epel/appstream). Venv + PyPI is used for the app's own deps anyway.
- No Go/Rust/Docker/Podman. Developer has **no passwordless sudo**; privileged steps are listed at the end for the user to run.
- Real config paths: `/etc/samba/smb.conf` (already contains `include = /etc/samba/usershares.conf` in `[global]`), `/etc/exports.d/` (exists, label `exports_t`), `/etc/vsftpd/{vsftpd.conf,user_list,ftpusers}` + `/etc/pam.d/vsftpd`, units `smb nmb nfs-server rpcbind vsftpd vsftpd@ avahi-daemon wsdd`. firewalld ships services `samba nfs mountd rpc-bind ftp mdns wsdd`. SELinux booleans: `nfs_export_all_rw` on; `samba_export_all_rw`, `ftpd_full_access`, `samba_enable_home_dirs` off. Default labels: `/usr/libexec/nasos/*` → `bin_t`, `/usr/lib/nasos/*` → `lib_t`, `/volume1` → `default_t` (needs an fcontext rule).

---

## Architecture in one paragraph

Three cooperating processes from one Python package `nasos`: **`nasos-web`** (FastAPI/uvicorn, unprivileged user `nasos`, owns SQLite, sessions, WebSocket, serves the UI), **`nasos-agent`** (root, socket-activated on `/run/nasos/agent.sock`, exposes a strictly typed JSON-RPC allowlist wrapping every privileged system adapter, runs the job queue, authenticates via PAM), and **`nasos-fileworker`** (spawned by the agent per logged-in user, drops to that user's uid/gid, performs all File Station I/O so the kernel enforces ownership/ACLs). Samba/NFS/mdadm config lives in NAS-OS-owned include files; vsftpd is owned wholesale. Storage is md → LVM → XFS mounted via generated systemd `.mount` units at `/volumeN`. Frontend: React + TS + Vite, custom window manager, Mantine components, Zustand for shell state, TanStack Query for server state. Ports follow DSM: 5000 (HTTP redirect) / 5001 (HTTPS).

---

## 1. Privilege model

**Unprivileged web + root agent + per-user file workers.** HTTP/WS/upload parsing never runs as root; the root surface is a finite RPC allowlist that is easy to audit and test with fakes; the agent is the natural parent for `setuid` workers.

| Unit | Runs as | Purpose |
|---|---|---|
| `nasos-agent.socket` | root; socket `root:nasos` `0660` | `ListenStream=/run/nasos/agent.sock`, `Accept=no` |
| `nasos-agent.service` | root, `Type=notify` | asyncio JSON-lines RPC server; job runner; spawns fileworkers; PAM auth |
| `nasos.service` | `User=nasos` | FastAPI/uvicorn on 5001 (TLS) + 5000 (redirect); `Requires=nasos-agent.socket`, `After=network-online.target` |
| `nasos-fileworker` (child of agent) | the logged-in user | File ops on `/run/nasos/workers/<uid>.sock`; idle timeout 15 min |

**RPC protocol (`nasos/rpc/`)**: `AF_UNIX` stream, newline-delimited JSON with request ids; optional binary frame (`{"bin": N}` header followed by N bytes) for file data. Peer check via `SO_PEERCRED` (uid `nasos` or 0; `nasos-task-run` from timers connects as root). Every method has Pydantic Params/Result models in `rpc/schemas.py` (`extra="forbid"`; paths validated against registered volume roots; usernames `^[a-z_][a-z0-9_-]{0,31}$`). The agent never receives shell strings: all adapters use `asyncio.create_subprocess_exec` with argv lists. Each call carries `ctx {user, role, ip}` and is journaled (`rpc users.create by admin@10.0.0.5 -> ok`). Events flow agent → web on the same connection (`job.progress`, `storage.changed`, `service.state`) and are fanned out by the web `EventBus`. `DirectTransport` calls handlers in-process (dev mode + tests).

**File Station as the logged-in user**: agent creates `/run/nasos/workers/<uid>.sock` (`nasos:nasos 0600`), execs `/usr/libexec/nasos/nasos-fileworker --uid N --listen-fd 3`; worker does `initgroups`, `setgid`, `setuid`, `prctl(PR_SET_NO_NEW_PRIVS)`, `umask 002`, then serves `files.*` methods. **Uploads and downloads stream through the worker** (binary frames, 1 MiB): the web process never writes to volumes, files are created by the user from the first byte (setgid dir + default ACLs apply), partial uploads live at `<dest>/.nasos-upload-<id>.part` and are `rename()`d on completion. FD passing (`socket.send_fds`) is a later optimization, not v1. Web reconnects via `agent.fileworker.ensure(uid)` on `ECONNREFUSED`.

**SELinux**: both daemons run as `unconfined_service_t` (launchers in `/usr/libexec/nasos/` are `bin_t`, so `init_t` transitions there); no custom policy in v1 (spike in M8). `nasos-setup` runs `semanage fcontext -a -t public_content_rw_t "/volume[0-9]+(/.*)?"` + `restorecon -R`, `setsebool -P samba_export_all_rw=on ftpd_full_access=on` (`samba_enable_home_dirs` only if home shares enabled). All config writes create the temp file **in the destination directory** then `rename()` so labels inherit, followed by `restorecon <path>`.

**systemd hardening** — `nasos.service`:
```
User=nasos Group=nasos SupplementaryGroups=systemd-journal
NoNewPrivileges=yes ProtectSystem=strict ProtectHome=yes PrivateTmp=yes PrivateDevices=yes
ProtectKernelTunables=yes ProtectKernelModules=yes ProtectControlGroups=yes ProtectClock=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 RestrictNamespaces=yes RestrictRealtime=yes
RestrictSUIDSGID=yes LockPersonality=yes SystemCallArchitectures=native SystemCallFilter=@system-service
CapabilityBoundingSet= AmbientCapabilities=
StateDirectory=nasos LogsDirectory=nasos RuntimeDirectory=nasos/web ReadOnlyPaths=/etc/nasos
```
(no `MemoryDenyWriteExecute`: CPython C extensions break). `nasos-agent.service`: `Type=notify Sockets=nasos-agent.socket PrivateTmp=yes ProtectControlGroups=yes ProtectKernelModules=yes RestrictRealtime=yes LockPersonality=yes SystemCallArchitectures=native RuntimeDirectory=nasos nasos/workers RuntimeDirectoryPreserve=yes KillMode=mixed OOMScoreAdjust=-500` (needs mount/setuid/CAP_SYS_ADMIN, so no `ProtectSystem`/`NoNewPrivileges`).

---

## 2. Config ownership strategy

`nasos/system/managedfile.py` → `ManagedFile(path, render, validate, apply)`: (1) render Jinja2 template with header `# Generated by NAS-OS <ver> at <ts>. DO NOT EDIT; local overrides go in <owner file>`; (2) write `<dir>/.<name>.nasos-tmp`, `fsync`, chmod/chown, `rename`, back up previous to `/var/lib/nasos/config-backups/<name>.<ts>` (keep 20); (3) `validate()` — on failure restore previous and raise `ConfigValidationError` with the tool's stderr (shown verbatim in UI); (4) `apply()` — if the unit fails to become active, roll back and re-apply previous; (5) store sha256 in `managed_files`; flag "modified outside NAS-OS" with a Regenerate button.

| Service | Ownership | Files | Validate | Apply |
|---|---|---|---|---|
| Samba | Include file | `/etc/samba/nasos.conf` (managed globals + one `[share]` per share). In `smb.conf` exactly one marker block as the last lines of `[global]`: `# BEGIN NASOS MANAGED` / `include = /etc/samba/nasos.conf` / `# END NASOS MANAGED` (mirrors the distro's `usershares.conf` include; our globals override earlier admin values, admin share sections survive) | `testparm -s --suppress-prompt` | `smbcontrol all reload-config`; `systemctl restart smb nmb` only when global network params change |
| NFS | Own file | `/etc/exports.d/nasos.exports`; never touch `/etc/exports` | dirs exist and are on registered volumes; `exportfs -ra` non-zero/stderr → rollback | `exportfs -ra` |
| vsftpd | Full template (no include support) | `/etc/vsftpd/vsftpd.conf` (RPM original saved as `vsftpd.conf.nasos-orig`), `/etc/vsftpd/user_list` (`userlist_enable=YES userlist_deny=NO`), `/etc/pam.d/nasos-ftp` (our PAM stack without `pam_shells`, `pam_service_name=nasos-ftp`), GUI "additional directives" textarea appended | `vsftpd <tmp> -olisten=NO -olisten_ipv6=NO </dev/null`, parse stderr for `unrecognised variable|bad (bool|numeric) value|500 OOPS` | `systemctl restart vsftpd` + `is-active` health check |
| mdadm | Own file | `/etc/mdadm.conf.d/nasos.conf` from `mdadm --detail --scan` | scan sanity | none (udev assembly) |
| systemd | Own units | `/etc/systemd/system/volumeN.mount`, `nasos-volumes.target`, `nasos-task-<id>.{service,timer}`, drop-ins `{smb,nfs-server,vsftpd}.service.d/nasos.conf` | `systemd-analyze verify` | `daemon-reload` + enable/start |
| avahi | Own file | `/etc/avahi/services/nasos.service` | XML well-formed | automatic (inotify) |

---

## 3. Identity and permission model

- **GUI users are real Linux users.** POSIX ownership/ACLs, Samba passdb and vsftpd all key off the Unix account.
- `/etc/pam.d/nasos`: `auth substack system-auth` / `account include system-auth` / `password substack system-auth` (`pam_faillock` lockout for free). Auth runs in the **agent** via `python-pam` (`service="nasos"`, in a thread). Web adds a per-ip+user token bucket.
- Groups from `/usr/lib/sysusers.d/nasos.conf`: `nasos` (service user), `nasos-admin`, `nasos-users`. `nasos-admin` → role admin; `nasos-users` → role user (File Station + own password); others and `root` refused. "NAS-managed" marker = membership in `nasos-users` + row in SQLite `users(uid, description, smb_enabled, ftp_enabled, created_by_nasos, smb_password_synced)`. Pre-existing accounts become visible via an admin "Import" action. No UID ranges.
- Create: `useradd -m -d <home_root>/<name> -s /sbin/nologin -G nasos-users -c "<desc>"` → `chpasswd` (stdin) → `smbpasswd -s -a` (stdin). Password change: Unix first, then `smbpasswd -s`; on Samba failure set `smb_password_synced=false` + notification + resync badge. Delete: `pdbedit -x` then `userdel [-r]`. `smb_enabled` ↔ `smbpasswd -d/-e`; `ftp_enabled` ↔ regenerate `user_list`. Nightly `pdbedit -L` reconciliation job. `nasos-setup` installs Samba by default so hashes exist from the first user.
- Sessions: server-side `sessions(token_hash, uid, username, role, created, last_seen, ip, ua)`, cookie `nasos_session` (HttpOnly, Secure in prod, SameSite=Lax), idle timeout 30 min; CSRF via required header `X-NASOS-Request: 1` on non-GET. Tokens are `secrets.token_urlsafe`; no JWT library.
- **Shared folder** = `/volumeN/<name>`, `root:nasos-users`, mode `2700` (not `2770`: POSIX ACLs share one mask between `group::` and every named entry, so a `group::rwx` from mode `2770` would hand every `nasos-users` member — i.e. every NAS-OS user — full access to every share regardless of `share_permissions`, verified experimentally during M2 research. Mode `2700` keeps `group::` empty; setgid still makes new files inherit the `nasos-users` group for bookkeeping, but real access comes only from the named ACL entries below, so "the kernel ACL is the security boundary" is actually true). Permissions in `share_permissions(share_id, principal_type, principal, level rw|ro|none)` applied with `setfacl` using the principal's **numeric** uid/gid, not name (a named entry for an unresolvable NSS name fails hard): `rw` → `u:<uid>:rwx` + `d:u:<uid>:rwx`; `ro` → `r-x` + default; `none` → entry removed (`setfacl -x u:<uid>,d:u:<uid>`, not set to a "none" ACL value); always reassert `m::rwx d:m::rwx o::--- d:o::---` (defensive — `setfacl -m` already recomputes the mask automatically unless `-n` is passed, which this adapter must never pass). Top-level applied synchronously, `setfacl -R` as a job with progress; a recursive re-apply job must explicitly include `u::`/`g::` too, not just the named/mask/other entries, since `-R` only touches entries it's explicitly given and won't normalize pre-existing content otherwise. Samba section: `path`, `valid users`, `read list`, `write list`, `inherit acls = yes`, `create mask = 0777`, `directory mask = 0777`, `browseable`, `guest ok = no` (the kernel ACL is the security boundary; lists are UX). NFS: per-client rules `nfs_rules(share_id, client, rw, squash, anonuid, anongid)` rendered as `<path> <client>(rw|ro,sync,no_subtree_check,root_squash|no_root_squash|all_squash,...)`.

---

## 4. Backend layout (`backend/nasos/`)

```
config.py            pydantic-settings; NASOS_MODE=prod|dev|test; reads /etc/nasos/nasos.toml
web/     main.py (create_app, lifespan: db, agent client, bus, sampler, static SPA)  deps.py  ws.py  static.py
api/     auth users groups shares smb nfs ftp files uploads storage monitor tasks network firewall discovery system notifications logs jobs
services/ users shares storage files tasks network audit notifications ...   (compose DB + agent RPC)
rpc/     schemas.py (all Params/Result models + Registry)  client.py (AgentClient, FileWorkerClient)  transport.py (Unix, Direct)
agent/   main.py (LISTEN_FDS, sd_notify, peer-cred)  dispatcher.py  jobs.py (JobRunner)  fileworker.py
         handlers/ auth users shares samba nfs vsftpd storage mounts network firewall discovery services tasks fileworker packages
system/  runner.py (argv-only subprocess)  managedfile.py  systemd.py (dasbus)  users.py acl.py samba.py nfs.py vsftpd.py
         smart.py lsblk.py mdadm.py lvm.py mkfs.py parted.py mounts.py nm.py (nmcli) firewall.py (python3-firewall)
         avahi.py wsdd.py packages.py selinux.py journal.py   distro/{base,rhel}.py (DistroAdapter)
         each adapter = Protocol + real impl + Fake* (fixture replay) for dev/test
db/      models.py session.py migrations/ (alembic)   SQLite WAL at /var/lib/nasos/nasos.db, opened only by web
events/bus.py   monitor/sampler.py ringbuffer.py   cli/{setup,taskrun,admin}.py
```

Decisions: **CLI JSON adapters for storage** (`lsblk -J -O -b`, `smartctl --json=c`, `lvs/vgs/pvs --reportformat json --units b`, `mdadm --detail --export`, `parted -s -j`, `findmnt -J`) rather than blivet/udisks2 — stable, fixture-friendly, cover v1; `pyudev.Monitor` for hotplug. **dasbus for systemd**, **nmcli for NetworkManager**, **`firewall.client.FirewallClient`** for firewalld. Tables: `users groups_meta shares share_permissions nfs_rules volumes disks_seen sessions jobs tasks task_runs uploads notifications audit_log managed_files settings metrics_5m`. Jobs run in the agent: bounded concurrency 4, per-resource locks (`disk:sda`, `share:media`), progress events ≤ every 500 ms, cancel where safe (never mid-`mkfs`); agent appends results to `/var/lib/nasos/agent/jobs.jsonl`, web reconciles via `jobs.list` at startup. Audit dependency on every mutating route; `SecretStr` for passwords. Blocking libs (pam, dasbus, firewall, psutil scans) via `asyncio.to_thread`. Deps (venv `--system-site-packages`, pinned in `pyproject.toml`/`requirements.lock`): fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, alembic, python-multipart, jinja2, psutil, cryptography, httpx (tests); from system: pam, dasbus, gi, firewall, pyudev, selinux.

---

## 5. Frontend layout (`frontend/`)

- Vite 7 + React 19 + TypeScript 5 (strict), pinned at scaffold time. **Zustand** for shell/window state, **TanStack Query v5** for server data (WS events → `invalidateQueries`). **Mantine 8** + `@tabler/icons-react` (CSS-variable theming → DSM skin is a token override), **TanStack Table + Virtual** for grids, `zod` at API boundaries, `tus-js-client`, `vitest` + testing-library, Playwright. Load the `frontend-design` skill before building the shell so the desktop has a deliberate visual identity, not a template look.
- **Custom window manager** `src/shell/wm/` (~800 LoC): store `{windows: {id, appId, title, x,y,w,h, z, state: normal|min|max, props}}`, actions open/close/focus/move/resize/minimize/maximize, pointer-capture drag/resize, single-instance apps, geometry in `localStorage`. `apps/registry.ts` manifests `{id, title, icon, component: lazy(), defaultSize, minSize, singleInstance, adminOnly}`.
- Shell: `Desktop.tsx Taskbar.tsx Launcher.tsx Login.tsx NotificationTray.tsx`. Apps: `dashboard/ control-panel/{users,groups,shared-folders,services,network,firewall,discovery,info}/ file-station/ storage-manager/ resource-monitor/ task-scheduler/ log-center/`. Shared components: `DataGrid WizardModal ConfirmDangerModal PermissionTable ByteSize`.
- **File Station**: tree sidebar (lazy `GET /files/list`), virtualized grid/list, breadcrumb, toolbar, details pane; HTML5 DnD (JSON of source paths; drop → `POST /files/move|copy` job), external drops via `webkitGetAsEntry()`; **tus 1.0 core** (creation/termination/expiration) in `api/uploads.py`, 16 MiB chunks, streamed to the fileworker, per-volume free-space check, hourly GC of stale `.part` files; download with Range, `POST /files/download-zip` (store-only zip streamed by worker); previews (image/pdf/video/audio via browser, text ≤ 2 MiB); ACL editor dialog → `files.set_acl` job.
- Serving: prod `StaticFiles("/usr/lib/nasos/ui")` + SPA fallback for non-`/api` paths; API `/api/v1`, WS `/api/v1/ws`; hashed assets immutable, `index.html` no-store. Dev: `vite dev` on 5173 proxying `/api` (ws: true) to the backend.

---

## 6. Storage Manager safety

- Inventory model `Disk{path, model, serial, wwn, size, rota, tran, smart{health,temp,attrs}, children}`, `Array`, `VG/LV`, `Volume{lv, fs, mountpoint, used}`; cache 5 s, invalidated by udev; SMART every 30 min + on demand with threshold notifications.
- **Protected set** (`services/storage/guard.py`, recomputed before plan and before execute): any device transitively hosting a mounted FS, swap, `/`, `/boot*`, `/var/lib/nasos`, an active md member, or a PV in a VG with active LVs → `409 device_protected`.
- **Two-phase execution**: `POST /storage/plans` → ordered steps with exact argv + data-loss summary, 5-min TTL, `confirm_token` = HMAC(plan JSON + expiry + device serials); UI shows the plan (this is the dry run), user types the disk serial or `ERASE`; `POST /storage/plans/{id}/execute` re-reads inventory and aborts on any serial/size mismatch; runs as a job; on failure stops without automatic teardown and offers a cleanup plan.
- Orchestration (default md + LVM + XFS; single-disk "basic" skips md): `wipefs -a` → `parted -s mklabel gpt mkpart nasos 1MiB 100% set 1 raid on` → `mdadm --create /dev/md/pool1 --level=<1|5|6|10> --raid-devices=N --metadata=1.2 --name=pool1 --run` (+ `mdadm.conf.d`, resync progress from `/proc/mdstat`) → `pvcreate; vgcreate nasos_pool1; lvcreate -l 100%FREE -n volume1` → `mkfs.xfs -L volume1` (ext4 selectable) → mount unit → fcontext + `restorecon` → `/volumeN/@nasos/tmp`.
- **Mount persistence via `.mount` units** (`What=UUID=… Where=/volumeN Type=xfs Options=defaults,noatime`, `WantedBy=nasos-volumes.target`; target `WantedBy=multi-user.target`; drop-ins for smb/nfs-server/vsftpd with `After=nasos-volumes.target RequiresMountsFor=/volume1 …`; names via `systemd-escape -p --suffix=mount`). A failed unit fails alone; a bad fstab line drops the host into emergency mode. `mdmonitor.service` enabled.
- Registering an existing mounted FS as a volume (M2, before Storage Manager exists): allowed if it is a mountpoint and not `/` or `/boot*`; NAS-OS never manages its mount.

---

## 7. Resource Monitor

psutil sampler in the web process (no privileges needed): 1 s CPU total/per-core, load, mem/swap, per-NIC bytes+pps, per-disk bytes+IOPS; 30 s volume usage; 5 s top-30 processes by CPU and RSS (`process_iter` + `oneshot`). Ring buffers 1 s×300, 10 s×360, 5 min×288 (downsampled; 5-min series persisted to `metrics_5m`, 30-day retention). WS topics `monitor.sample` (interval 1|5) and `monitor.processes` (only while tab open), compact array payloads; `GET /monitor/history?series=…&range=1h` seeds charts.

## 8. Task Scheduler and backup

SQLite is the source of truth; schedules **materialize to systemd timers**: `nasos-task-<id>.timer` (`OnCalendar`, `Persistent=true`, `RandomizedDelaySec=30`) + `.service` (`Type=oneshot`, `ExecStart=/usr/libexec/nasos/nasos-task-run <id>`), `OnCalendar` validated with `systemd-analyze calendar`. `nasos-task-run` calls `tasks.run(id, trigger="timer")` on the agent socket so "Run now", timers and history share one job path. rsync: `rsync -a -H -A -X --info=progress2 --stats [--delete] [-e "ssh -i /var/lib/nasos/ssh/id_ed25519 -o UserKnownHostsFile=/var/lib/nasos/ssh/known_hosts"] src dst`, progress parsed on `\r` with regex `(\d[\d,]*)\s+(\d+)%\s+([\d.]+\w+/s)\s+(\d+:\d+:\d+).*xfr#(\d+), (?:to-chk|ir-chk)=(\d+)/(\d+)`, `--stats` → `task_runs`, full log `/var/log/nasos/tasks/<run_id>.log` (logrotate shipped). Destinations: volume path, `user@host:path` (key from `nasos-setup`, host key pinned on first use with confirmation), `rsync://`. Script tasks via `systemd-run --uid=<run_as> --pipe`.

## 9. Network, firewall, discovery

Hostname via `hostnamectl set-hostname` (then regenerate avahi + Samba `netbios name`). NetworkManager via `nmcli -t -g` reads and `nmcli connection modify <uuid> ipv4.method manual ipv4.addresses A/P ipv4.gateway G ipv4.dns "…"` + `connection up`; for the interface serving the session, arm `systemd-run --on-active=90 --unit=nasos-net-revert-<uuid> …` and cancel via `network.confirm` once the UI reaches `/system/ping` on the new address. firewalld via `FirewallClient` (permanent + runtime): SMB→`samba`, NFS→`nfs mountd rpc-bind`, FTP→`ftp` + passive port range `30000-30100/tcp` (matches `pasv_min_port/max`), mDNS→`mdns`, WS-Discovery→`wsdd`, GUI→shipped `/usr/lib/firewalld/services/nasos.xml` (5000/5001); global "manage firewall: yes/no". Discovery: `/etc/avahi/services/nasos.service` (`_smb._tcp`, `_device-info._tcp model=Xserve`, `_https._tcp` 5001, `_nfs._tcp`/`_ftp._tcp` when enabled); wsdd via `/etc/sysconfig/wsdd` `OPTIONS="--workgroup WG --hostname NAME"` (follows smb lifecycle via `BindsTo`).

---

## 10. Packaging, install, dev workflow

- On disk: `/usr/lib/nasos/venv` (`--system-site-packages`), `/usr/lib/nasos/ui`, `/usr/libexec/nasos/{nasos-web,nasos-agent,nasos-fileworker,nasos-task-run,nasos-setup}` (3-line launchers, `bin_t`), `/etc/nasos/nasos.toml`, `/etc/nasos/tls/{cert,key}.pem` (`0640 root:nasos`), `/etc/pam.d/{nasos,nasos-ftp}`, `/usr/lib/sysusers.d/nasos.conf`, `/usr/lib/tmpfiles.d/nasos.conf` (`/run/nasos`, `/run/nasos/workers 0750 root nasos`, `/var/lib/nasos 0750 nasos nasos`, `/var/log/nasos`), `/usr/lib/firewalld/services/nasos.xml`, units, `/etc/logrotate.d/nasos`.
- **RPM** `packaging/rpm/nasos.spec`: `BuildRequires python3-devel nodejs>=20 npm`; build = `npm ci && npm run build`, `python3 -m venv --system-site-packages %{buildroot}/usr/lib/nasos/venv && pip install --no-index --find-links packaging/wheels -r requirements.lock .`, fix shebangs; `%global __requires_exclude ^/usr/lib/nasos/venv/.*`, `__provides_exclude_from` likewise, `%undefine __brp_mangle_shebangs`, `_build_id_links none`. `Requires`: python3>=3.12, python3-dasbus, python3-gobject, python3-firewall, python3-pam, python3-pyudev, python3-libselinux, policycoreutils-python-utils, systemd, firewalld, NetworkManager, nfs-utils, mdadm, lvm2, xfsprogs, e2fsprogs, parted, util-linux, acl, shadow-utils, smartmontools, rsync, avahi; `Recommends: samba samba-common-tools wsdd`; `Suggests: vsftpd`. `%post`: `systemd-sysusers`, `systemd-tmpfiles --create`, `%systemd_post`. Wheelhouse built by `make vendor` (gitignored). CI builds via `mock -r rocky-10-x86_64`.
- **`nasos-setup`** (root, idempotent, `--non-interactive` flags): detect distro → offer `dnf install samba samba-common-tools` (default yes) / `vsftpd` (default no) → SELinux booleans + fcontext → write `nasos.toml` → self-signed EC P-256 cert (10 y, SAN hostname + `nasos.local` + IPs) → first admin (`nasos-admin,nasos-users`, `chpasswd`, `smbpasswd -a`) → Samba include block, enable `smb nmb` → `firewall-cmd --permanent --add-service=nasos && --reload` → `systemctl enable --now nasos-agent.socket nasos.service` → print URL. Logs each command before running it.
- **Dev without passwordless sudo**: (1) default `NASOS_MODE=dev` (`make dev`): web + agent handlers in one process via `DirectTransport`, **all system adapters are fakes** (`FakeRunner` replays `backend/tests/fixtures/`, `FakeSamba`/`FakeNfs`/`FakeVsftpd` write under `./devdata/etc/`, `FakeSystemd`), file ops against `./devdata/volume1` as the current user, PAM replaced by `devusers.toml`, cookies non-Secure; `uvicorn --reload` + `vite dev`. (2) `packaging/dev/nasos-agent-dev.{service,socket}` (`SocketGroup=harwinder SocketMode=0660`, `--dev` refuses destructive ops except devices in `NASOS_DEV_DISKS`), installed once with `sudo make dev-agent-install`. (3) `make loopdisks` prints `losetup` commands for 4 file-backed loop devices. Node: `sudo dnf install nodejs npm` preferred; fallback `make bootstrap-node` downloads the Node 22 tarball into `~/.local/node` (no sudo).

---

## 11. Repository layout and testing

```
NAS-OS/  README.md LICENSE(MIT) Makefile .gitignore .editorconfig .pre-commit-config.yaml
  backend/  pyproject.toml (hatchling; console_scripts nasos-web nasos-agent nasos-fileworker nasos-task-run nasos-setup nasos-cli)
            requirements.lock  alembic.ini  nasos/ (section 4)  tests/{unit,api,fixtures}/
  frontend/ package.json vite.config.ts tsconfig.json index.html src/{main.tsx,app,api,shell,apps,components,stores,theme} tests/ e2e/
  packaging/ rpm/nasos.spec systemd/ sysusers.d/ tmpfiles.d/ firewalld/ pam.d/ logrotate/ libexec/ dev/ selinux/README.md wheels/(gitignored)
  docs/ architecture.md privilege-model.md config-ownership.md storage.md api.md dev-setup.md selinux.md debian-porting.md
  tests/integration/ (pytest over SSH/local socket against real services)  tests/vm/ (libvirt Rocky 10 cloud-init, 4 extra disks)
  .github/workflows/ci.yml
```

Testing: **unit/API on every push** (pytest with fakes; each `system/*` adapter has Protocol + real + Fake; golden files for every rendered config and unit; fixture-driven parsers; vitest for WM store and hooks; Playwright smoke against `make dev`). **System tests in CI**: privileged `rockylinux/rockylinux:10` container with systemd as PID 1, install the RPM, real samba/nfs/vsftpd, md on loop devices. **SELinux/VM nightly**: libvirt VM, assert `getenforce == Enforcing` and zero `ausearch -m AVC` after the suite.

---

## 12. Milestones (executed sequentially; gate must pass before the next)

| # | Milestone | Delivers | Gate | Size |
|---|---|---|---|---|
| 1 | **Skeleton** | `git init`, README, MIT LICENSE, Makefile, `.gitignore`; `pyproject`, `config.py`, `rpc/schemas.py` + transports + client, `agent/main.py` + dispatcher + `handlers/auth.py` (PAM) + `system.info`, `db/models.py` (sessions, audit_log, settings, notifications) + first migration, `web/main.py` + `deps.py` + `api/{auth,system}.py` + `ws.py` + `events/bus.py` + `monitor/sampler.py`, sessions/RBAC/CSRF, audit log; frontend: Vite scaffold, login, desktop shell (WM, taskbar, launcher), Dashboard (hostname, uptime, live CPU/mem), Control Panel → Info Center; dev mode with fakes; `packaging/` units + spec + minimal `nasos-setup`; CI unit tests | `make dev` serves login → desktop → dashboard with live graph; `pytest` and `vitest` green; RPM spec lints (`rpmlint`) | M |
| 2 | **Users, groups, shares, SMB** | users/groups CRUD + password sync, Import existing user, manual volume registration, shares + ACL model + `setfacl` job, `nasos.conf` include + testparm + reload, service start/enable, firewalld `samba`, notifications tray | golden-file tests for `nasos.conf`; API tests for the permission matrix; dev UI walkthrough | L |
| 3 | **File Station** | fileworker lifecycle (spawn/reap/reconnect), browse/search/sort, mkdir/rename/delete/copy/move jobs, tus upload streamed to worker, download + zip, previews, ACL editor, properties | upload/download 1 GiB file in dev mode with progress; resumable after refresh; ownership correct | L |
| 4 | **Storage Manager** | inventory + SMART + hotplug, guard, plan/execute + confirm token, md/LVM/mkfs/mount units, auto volume registration, health notifications, resync progress | fixture tests for inventory merge + guard; golden `.mount`/target/drop-ins; plan preview renders exact argv | XL |
| 5 | **NFS, FTP, Network, Firewall, Discovery** | exports.d + rules UI, vsftpd template + user_list + PAM, nmcli config + revert timer, firewalld toggles, avahi/wsdd | golden files for exports/vsftpd.conf/avahi XML; API tests for revert flow | M |
| 6 | **Resource Monitor + Log Center** | ring buffers, WS streams, charts, processes tab; journald viewer (`journalctl -o json`) with filters/export; audit viewer | WS delivers 1 s samples for 5 min without leak; history endpoint seeds charts | M |
| 7 | **Task Scheduler + rsync backup** | timer/service generation, `nasos-task-run`, rsync runner + parser, SSH key mgmt, history + logs | parser fixtures; golden timer/service; dev-mode rsync between two devdata dirs shows progress | M |
| 8 | **Hardening + release** | integration suite (`tests/integration`, `tests/vm`), upgrade path (alembic + config regeneration), external-modification detection UI, cert management, docs, `nasos_t` policy spike notes, 1.0 RPM build | CI green incl. container system tests; `mock` build produces installable RPM | M |

Milestone 1 task order: `pyproject` + `config.py` → `rpc/schemas.py` + `transport.py` + `client.py` → `agent/main.py` + `dispatcher.py` + `handlers/auth.py` → `db/models.py` + migration → `web/main.py`, `deps.py`, `api/auth.py`, `api/system.py`, `ws.py`, `events/bus.py`, `monitor/sampler.py` → frontend shell (`wm/store.ts`, `Window.tsx`, `Desktop.tsx`, `Taskbar.tsx`, `Launcher.tsx`, `Login.tsx`, `apps/registry.ts`, `apps/dashboard`) → `packaging/` + `cli/setup.py` → CI.

Critical files everything else depends on: `backend/nasos/rpc/schemas.py`, `backend/nasos/agent/main.py`, `backend/nasos/system/managedfile.py`, `backend/nasos/web/main.py`, `frontend/src/shell/wm/store.ts`.

---

## 13. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| SELinux denials in the field | `unconfined_service_t` daemons; `public_content_rw_t` volumes; booleans set by setup; same-dir temp + rename; VM suite asserts zero AVCs; Log Center surfaces `ausearch -m AVC` |
| Samba password DB drift | Samba installed before users; one RPC sets both; `smb_password_synced` flag + resync UI; nightly `pdbedit -L` reconciliation |
| Clobbering admin config | include files; single marker block; vsftpd original preserved + extra-directives field; sha256 tamper detection; backups + validation + rollback |
| Running as root | only the agent; strict RPC schemas + argv-only subprocesses; peer-cred check; every RPC journaled; workers drop privileges with `NO_NEW_PRIVS` |
| NFS root_squash / uid mismatch | `root_squash` default; UI explains host-based semantics; `all_squash` maps to a chosen NAS user; `o::---` in ACLs |
| Large uploads | tus resumable chunks streamed to the worker; no buffering in memory; free-space check; hourly `.part` GC |
| Destroying the wrong disk | protected-set guard; plan preview with exact commands; HMAC token bound to serials; re-validation before execute; `--dev` device allowlist |
| Boot fragility | `.mount` units + `nasos-volumes.target`, never fstab; `mdadm.conf.d`; `RequiresMountsFor` drop-ins |
| Losing GUI after network change | 90 s `systemd-run` revert timer cancelled only from the new address |
| Distro drift | `DistroAdapter` for package/unit names, paths, security hooks; CI matrix Rocky 10 + Fedora |
| Deps not in RHEL repos | vendored wheelhouse; venv `--system-site-packages`; `__requires_exclude` |
| WS fan-out cost | topic subscriptions, server-side throttling, streams only while windows open, array payloads |

---

## Verification (end to end)

1. **Every milestone**: `make test` (`pytest backend/tests`, `npm test` in `frontend/`), `make lint` (ruff, mypy, eslint, tsc), golden-file diffs for rendered configs/units.
2. **Dev mode UI**: `make dev` (backend on 5001 dev, Vite on 5173), then verify in the browser with the Chrome MCP tools: login with a `devusers.toml` account, open each app window, exercise the milestone's feature (create user/share, upload/download in File Station, plan a storage change against fixture disks, watch Resource Monitor stream, run an rsync task between two devdata folders). Capture screenshots for the final report.
3. **Playwright smoke** (`make e2e`) covering login → open app → CRUD flow per milestone.
4. **Real-system checks that need the user's sudo** (cannot run autonomously on this box):
   ```
   sudo dnf install -y nodejs npm samba samba-common-tools vsftpd      # toolchain + services
   sudo make dev-agent-install && sudo systemctl start nasos-agent-dev   # privileged dev agent
   sudo make loopdisks                                                   # 4 loop devices for md/LVM tests
   sudo dnf install -y qemu-kvm libvirt virt-install && make vm-test     # SELinux-enforcing VM suite (M8)
   ```
   Until these are run, backend work is validated against fakes and golden files; the plan flags each real-system gate explicitly in the milestone report.
5. **Release check (M8)**: `make rpm` via `mock`, install in the VM, run `nasos-setup --non-interactive`, log in over HTTPS on 5001, create a share, connect from an SMB/NFS/FTP client, confirm `ausearch -m AVC` is empty.
