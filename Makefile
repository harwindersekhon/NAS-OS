.PHONY: bootstrap bootstrap-node dev test test-backend test-frontend \
        lint lint-backend lint-frontend format build \
        loopdisks dev-agent-install vendor rpm rpmlint e2e clean

PYTHON      ?= python3.12
REPO_ROOT   := $(CURDIR)

## --- Setup -----------------------------------------------------------

bootstrap: backend/.venv frontend/node_modules

backend/.venv:
	$(PYTHON) -m venv --system-site-packages backend/.venv
	backend/.venv/bin/pip install --upgrade pip
	backend/.venv/bin/pip install -e "./backend[dev]"

frontend/node_modules:
	cd frontend && npm install

bootstrap-node:
	packaging/dev/bootstrap-node.sh

## --- Dev ---------------------------------------------------------------

dev: backend/.venv frontend/node_modules
	packaging/dev/run-dev-servers.sh

## --- Test / lint ---------------------------------------------------------

test: test-backend test-frontend

test-backend: backend/.venv
	cd backend && .venv/bin/pytest

test-frontend: frontend/node_modules
	cd frontend && npm test

lint: lint-backend lint-frontend

lint-backend: backend/.venv
	cd backend && .venv/bin/ruff check nasos tests
	cd backend && .venv/bin/mypy nasos tests

lint-frontend: frontend/node_modules
	cd frontend && npm run lint
	cd frontend && npm run typecheck

format: backend/.venv frontend/node_modules
	cd backend && .venv/bin/ruff format nasos tests
	cd frontend && npm run format

e2e: backend/.venv frontend/node_modules
	cd frontend && npx playwright install --with-deps chromium
	cd frontend && npm run e2e

## --- Build / package -----------------------------------------------------

build: frontend/node_modules
	cd frontend && npm run build

# Loop devices for md/LVM testing against the dev agent (Milestone 4+).
# Needs root; prints the commands rather than running them.
loopdisks:
	@echo "Run as root to create 4 file-backed loop devices:"
	@mkdir -p backend/devdata
	@for i in 1 2 3 4; do \
	  img=$(REPO_ROOT)/backend/devdata/loop$$i.img; \
	  echo "  truncate -s 2G $$img && losetup -f --show $$img"; \
	done

# Installs the privileged dev agent (real system adapters, dev auth) as a
# systemd unit whose socket only your own user can reach — PLAN.md §10.
dev-agent-install:
	sed -e 's|@REPO_ROOT@|$(REPO_ROOT)|g' -e 's|@DEV_GROUP@|$(shell id -gn)|g' \
	  packaging/dev/nasos-agent-dev.service | sudo tee /etc/systemd/system/nasos-agent-dev.service >/dev/null
	sed -e 's|@DEV_GROUP@|$(shell id -gn)|g' \
	  packaging/dev/nasos-agent-dev.socket | sudo tee /etc/systemd/system/nasos-agent-dev.socket >/dev/null
	sudo systemctl daemon-reload
	@echo "Installed. Start it with: sudo systemctl start nasos-agent-dev.socket"

# Wheelhouse for the RPM's offline `pip install --no-index`. Gitignored.
vendor: backend/.venv
	mkdir -p packaging/wheels
	backend/.venv/bin/pip download -d packaging/wheels -r backend/requirements.lock

# Needs `mock` configured for rocky-10-x86_64 (not available in this dev
# sandbox — see PLAN.md §11 CI notes / README "Real-system checks").
rpm: vendor
	rm -rf dist && mkdir -p dist
	git archive --prefix=nasos-0.1.0/ -o dist/nasos-0.1.0.tar.gz HEAD
	mock -r rocky-10-x86_64 --buildsrpm --spec packaging/rpm/nasos.spec \
	  -D "_sourcedir $(REPO_ROOT)/dist" --resultdir dist
	mock -r rocky-10-x86_64 --rebuild dist/nasos-0.1.0-1*.src.rpm --resultdir dist

rpmlint:
	rpmlint packaging/rpm/nasos.spec

clean:
	rm -rf backend/.venv frontend/node_modules frontend/dist dist \
	  backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
