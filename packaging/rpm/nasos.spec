Name:           nasos
Version:        0.1.0
Release:        1%{?dist}
Summary:        DSM-style NAS management system

License:        MIT
URL:            https://github.com/nasos-project/nasos
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel >= 3.12
BuildRequires:  nodejs >= 20
BuildRequires:  npm
BuildRequires:  systemd-rpm-macros

Requires:       python3 >= 3.12
Requires:       python3-dasbus
Requires:       python3-gobject
Requires:       python3-firewall
Requires:       python3-pam
Requires:       python3-pyudev
Requires:       python3-libselinux
Requires:       policycoreutils-python-utils
Requires:       systemd
Requires:       firewalld
Requires:       NetworkManager
Requires:       nfs-utils
Requires:       mdadm
Requires:       lvm2
Requires:       xfsprogs
Requires:       e2fsprogs
Requires:       parted
Requires:       util-linux
Requires:       acl
Requires:       shadow-utils
Requires:       smartmontools
Requires:       rsync
Requires:       avahi
Recommends:     samba
Recommends:     samba-common-tools
Recommends:     wsdd
Suggests:       vsftpd

%{?systemd_requires}

# The venv is a self-contained deployment: its dependency graph must
# neither leak into, nor be satisfiable from, the RPM's own Provides/Requires.
%global __requires_exclude ^/usr/lib/nasos/venv/.*$
%global __provides_exclude_from ^/usr/lib/nasos/venv/.*$
%undefine __brp_mangle_shebangs
%global _build_id_links none

%description
NAS-OS is an open-source, Synology DiskStation Manager (DSM)-like NAS
management system that installs on an existing Linux server and provides
a browser-based, desktop-style GUI to manage shared folders, users and
groups, permissions, SMB, NFS, FTP, storage (disks/RAID/LVM), resource
monitoring, scheduled tasks and rsync backups, and network/firewall
settings.

%prep
%autosetup -n %{name}-%{version}

%build
pushd frontend
npm ci
npm run build
popd

python3 -m venv --system-site-packages venv-build
venv-build/bin/pip install --no-index --find-links packaging/wheels \
    -r backend/requirements.lock
venv-build/bin/pip install --no-index --find-links packaging/wheels ./backend

%install
install -d -m 0755 %{buildroot}%{_prefix}/lib/%{name}
cp -a venv-build %{buildroot}%{_prefix}/lib/%{name}/venv
find %{buildroot}%{_prefix}/lib/%{name}/venv/bin -maxdepth 1 -type f -exec chmod 0755 {} \;

install -d -m 0755 %{buildroot}%{_prefix}/lib/%{name}/ui
cp -a frontend/dist/. %{buildroot}%{_prefix}/lib/%{name}/ui/

install -d -m 0755 %{buildroot}%{_libexecdir}/%{name}
install -m 0755 packaging/libexec/* %{buildroot}%{_libexecdir}/%{name}/

install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 packaging/systemd/nasos-agent.socket \
                packaging/systemd/nasos-agent.service \
                packaging/systemd/nasos.service \
                %{buildroot}%{_unitdir}/

install -d -m 0755 %{buildroot}%{_prefix}/lib/sysusers.d
install -m 0644 packaging/sysusers.d/nasos.conf \
    %{buildroot}%{_prefix}/lib/sysusers.d/%{name}.conf

install -d -m 0755 %{buildroot}%{_prefix}/lib/tmpfiles.d
install -m 0644 packaging/tmpfiles.d/nasos.conf \
    %{buildroot}%{_prefix}/lib/tmpfiles.d/%{name}.conf

install -d -m 0755 %{buildroot}%{_prefix}/lib/firewalld/services
install -m 0644 packaging/firewalld/nasos.xml \
    %{buildroot}%{_prefix}/lib/firewalld/services/%{name}.xml

install -d -m 0755 %{buildroot}%{_sysconfdir}/pam.d
install -m 0644 packaging/pam.d/nasos %{buildroot}%{_sysconfdir}/pam.d/nasos

install -d -m 0755 %{buildroot}%{_sysconfdir}/%{name}
install -d -m 0750 %{buildroot}%{_sysconfdir}/%{name}/tls
touch %{buildroot}%{_sysconfdir}/%{name}/nasos.toml

%pre
%sysusers_create_compat packaging/sysusers.d/nasos.conf

%post
%systemd_post nasos-agent.socket nasos.service
%tmpfiles_create packaging/tmpfiles.d/nasos.conf

%preun
%systemd_preun nasos-agent.socket nasos.service

%postun
%systemd_postun_with_restart nasos-agent.socket nasos.service

%files
%license LICENSE
%doc README.md
%{_prefix}/lib/%{name}/
%{_libexecdir}/%{name}/
%{_unitdir}/nasos-agent.socket
%{_unitdir}/nasos-agent.service
%{_unitdir}/nasos.service
%{_prefix}/lib/sysusers.d/%{name}.conf
%{_prefix}/lib/tmpfiles.d/%{name}.conf
%{_prefix}/lib/firewalld/services/%{name}.xml
%config(noreplace) %{_sysconfdir}/pam.d/nasos
%dir %{_sysconfdir}/%{name}
%dir %attr(0750,root,nasos) %{_sysconfdir}/%{name}/tls
%config(noreplace) %{_sysconfdir}/%{name}/nasos.toml

%changelog
* Sat Sep 19 2026 NAS-OS contributors <noreply@example.com> - 0.1.0-1
- Milestone 1: skeleton (auth, sessions, dashboard, agent RPC, dev mode)
