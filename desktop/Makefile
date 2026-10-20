# Desktop app build targets
.PHONY: help install dev release clean build check

# Cygwin and MSYS cannot exec the npm shell script when Node lives under
# "Program Files". cmd.exe runs npm.cmd, which does not depend on that path.
_UNAME := $(shell uname -s 2>/dev/null)
ifeq ($(origin NPM),undefined)
  ifneq (,$(filter CYGWIN% MINGW% MSYS%,$(_UNAME)))
    NPM := cmd.exe /c npm.cmd
  else
    NPM := npm
  endif
endif
# Tauri invokes cargo. On Windows that cargo must see desktop msvcrt.lib.
ifeq ($(origin NPM_BUILD),undefined)
  ifneq (,$(filter CYGWIN% MINGW% MSYS%,$(_UNAME)))
    NPM_BUILD := cmd.exe /c scripts\\with-msvc.cmd npm.cmd
  else
    NPM_BUILD := $(NPM)
  endif
endif

CONTAINER_RUNTIME ?= podman
CARGO_MANIFEST := src-tauri/Cargo.toml
# Visual Studio 2026 can be selected by rustc while shipping only OneCore
# libraries. vcvars from the desktop C++ toolset supplies msvcrt.lib.
ifeq ($(origin CARGO),undefined)
  ifneq (,$(filter CYGWIN% MINGW% MSYS%,$(_UNAME)))
    CARGO := cmd.exe /c scripts\\with-msvc.cmd cargo
  else
    CARGO := cargo
  endif
endif

help:
	@echo "Agent Control Desktop (Tauri 2 + Podman)"
	@echo ""
	@echo "Targets:"
	@echo "  make install       - Install Node and Rust dependencies"
	@echo "  make dev           - Run dev with hot reload (requires Podman running)"
	@echo "  make build         - Build for current platform"
	@echo "  make release       - Build production release (with Podman bundled on Windows)"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Options:"
	@echo "  CONTAINER_RUNTIME=podman  (default, or set to 'docker')"

install:
	$(NPM) install
	mkdir -p dist
	$(CARGO) build --manifest-path $(CARGO_MANIFEST)

dev:
	CONTAINER_RUNTIME=$(CONTAINER_RUNTIME) $(NPM_BUILD) run dev

build:
	mkdir -p dist
	printf '%s\n' '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Agent Control</title></head><body><div id="root"></div></body></html>' > dist/index.html
	CONTAINER_RUNTIME=$(CONTAINER_RUNTIME) $(NPM_BUILD) run build

release:
	mkdir -p dist
	printf '%s\n' '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Agent Control</title></head><body><div id="root"></div></body></html>' > dist/index.html
	CONTAINER_RUNTIME=$(CONTAINER_RUNTIME) $(NPM_BUILD) run release

clean:
	rm -rf node_modules
	rm -rf src-tauri/target
	rm -rf dist
	rm -rf src-tauri/gen

check:
	$(CARGO) clippy --manifest-path $(CARGO_MANIFEST)
	$(CARGO) fmt --manifest-path $(CARGO_MANIFEST) --check
