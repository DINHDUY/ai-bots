# Venv layout is detected from the OS; override with: make BIN=<path> <target>
PYTHON ?= python
UV ?= uv
VENV := .venv
ifeq ($(OS),Windows_NT)
BIN := $(VENV)/Scripts
else
BIN := $(VENV)/bin
endif
PIP := $(BIN)/python -m pip
PY := $(BIN)/python
IMAGE_REGISTRY ?= ghcr.io/dinhduy
IMAGE_TAG ?= latest
SANDBOX_IMAGE_NAME := $(IMAGE_REGISTRY)/agentbot-sandbox

.PHONY: help venv install env sandbox docker-build docker-push dev-setup control gateway dev test test-docker behave frontend-install frontend-dev frontend-build check check-docker hooks

help:
	@echo Targets: venv install env sandbox docker-build docker-push control gateway dev-setup dev test test-docker behave frontend-install frontend-dev frontend-build check check-docker hooks

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(UV) sync --locked
	$(PY) -I -c "import agentbot_control.app; print('Agent Control installation verified')"

env:
	$(BIN)/python -c "import shutil; shutil.copyfile('.env.example', '.env')"

# Creates .env only when absent so existing secrets are never overwritten.
.env:
	$(MAKE) env

# Also tags the unprefixed local name, which SANDBOX_IMAGE defaults to.
docker-build:
	docker build -f docker/sandbox/Dockerfile -t $(SANDBOX_IMAGE_NAME):$(IMAGE_TAG) -t agentbot-sandbox .

# Requires prior login: docker login ghcr.io
docker-push: docker-build
	docker push $(SANDBOX_IMAGE_NAME):$(IMAGE_TAG)

sandbox: docker-build

control:
	$(BIN)/agentbot-control

gateway:
	$(BIN)/agentbot

dev-setup:
	$(MAKE) install
	$(MAKE) .env
	$(MAKE) frontend-install
	$(MAKE) sandbox

# Sets up env, packages and sandbox image, then runs backend (8000) and frontend (5173); Ctrl-C stops both.
dev: dev-setup
	$(MAKE) -j2 control frontend-dev

test:
	$(PY) -m pytest

test-docker:
	$(PY) -m pytest -m docker

behave:
	$(BIN)/behave

frontend-install:
	npm ci --prefix packages/agent-control-frontend

frontend-dev:
	npm run dev --prefix packages/agent-control-frontend

frontend-build:
	npm run build --prefix packages/agent-control-frontend

check:
	$(PY) -m ruff check packages deploy docs/usecases scripts tests conftest.py
	$(PY) scripts/check_python_size.py
	$(PY) -m pyright
	$(PY) -m pyright --project pyrightconfig.foundation.json
	$(PY) -m pytest -m "not docker and not windows_desktop and not macos_desktop"
	$(PY) scripts/docs_check.py
	$(PY) scripts/verify_core.py
	$(PY) scripts/check_wire.py
	npm run lint --prefix packages/agent-control-frontend
	npm run build --prefix packages/agent-control-frontend
	npm test --prefix packages/agent-control-frontend

check-docker:
	$(PY) -m pytest -m docker --require-docker
	npm run test:e2e --prefix packages/agent-control-frontend

hooks:
	$(BIN)/pre-commit install

.PHONY: windows-setup windows-companion windows-test
windows-setup:
	powershell -NoProfile -File scripts/windows-companion.ps1 setup

windows-companion:
	powershell -NoProfile -File scripts/windows-companion.ps1 run

windows-test:
	powershell -NoProfile -File scripts/windows-companion.ps1 test

.PHONY: azure-install azure-test cloud-host-bundle
azure-install:
	$(UV) sync --locked --extra azure --package agent-control-backend

azure-test:
	$(PY) -m pytest packages/agent-control-backend/tests/test_cloud.py packages/agentbot-computer-agent/tests

cloud-host-bundle:
	$(PYTHON) deploy/azure/build-host-bundle.py

.PHONY: docs-check metrics
docs-check:
	$(PY) scripts/docs_check.py

metrics:
	$(PY) scripts/arch_metrics.py

.PHONY: macos-setup macos-companion macos-test macos-bridge-test
macos-setup:
	$(PY) scripts/macos_setup.py

macos-companion:
	data/oi/venv/bin/agentbot-macos run

macos-test:
	$(UV) pip install --python data/oi/venv/bin/python --require-hashes -r packages/agentbot-macOS-companion/requirements-test.lock
	AGENTBOT_MACOS_DESKTOP_TEST=1 data/oi/venv/bin/python -m pytest packages/agentbot-macOS-companion/tests -m macos_desktop --require-macos-desktop

macos-bridge-test:
	data/oi/venv/bin/python scripts/macos_taskstar_probe.py
