# Purpose: The complete development workflow for Waitarr.
# Origin: rendered by starter-kits (kit poc, stack python-cli), then aligned
# on qbit-ops' harness -- see docs/adr/0009-harness.md.

SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c
MAKEFLAGS += --no-print-directory
.DEFAULT_GOAL := help

PROJECT_NAME := waitarr
PY := poetry run
PY_PATHS := scripts src tests
IMAGE ?= waitarr:local
PLATFORMS ?= linux/amd64,linux/arm64

.PHONY: help doctor info install hooks-install sync run format lint test \
	test-docker check check-fast check-version check-docs check-ai secrets \
	deps-audit vulns social-preview build check-dist check-image image image-multiarch ci \
	ci-entrypoint clean

.sync-stamp: pyproject.toml poetry.lock
	@poetry install --sync --no-interaction
	@touch .sync-stamp

sync: .sync-stamp ## dev: Sync the virtualenv when pyproject.toml or poetry.lock changes

# One help section per category tag; every documented target carries one
# of dev/qa/use/diag (enforced by tests/unit/test_makefile.py).
define help_section
@echo "$(1):"
@grep -hE '^[a-zA-Z0-9_-]+:.*?## $(2): ' $(MAKEFILE_LIST) \
	| sort -t: -k1,1 \
	| awk 'BEGIN {FS = ":.*?## $(2): "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
@echo ""
endef

help: ## diag: Show this help
	$(call help_section,Development,dev)
	$(call help_section,Quality,qa)
	$(call help_section,Local usage,use)
	$(call help_section,Diagnostics,diag)

doctor: ## diag: Check required local tools
	@missing=0; \
	for command in git make python3 poetry docker; do \
		if command -v "$$command" >/dev/null 2>&1; then \
			printf '[OK] %s\n' "$$command"; \
		else \
			printf '[MISSING] %s\n' "$$command" >&2; \
			missing=1; \
		fi; \
	done; \
	exit "$$missing"

info: ## diag: Show project and environment information
	@printf 'Project: %s\n' "$(PROJECT_NAME)"
	@printf 'Version: %s\n' "$$(poetry version -s 2>/dev/null || echo unknown)"
	@printf 'Python: %s\n' "$$(python3 --version 2>&1)"
	@printf 'Branch: %s\n' "$$(git branch --show-current 2>/dev/null || true)"

install: doctor ## dev: Install dependencies and configure Git hooks
	@poetry install --no-interaction
	@touch .sync-stamp
	@$(PY) pre-commit install --hook-type pre-commit --hook-type commit-msg

hooks-install: ## dev: Reinstall the Git hooks
	@$(PY) pre-commit install --hook-type pre-commit --hook-type commit-msg

run: sync ## use: Run Waitarr with ./waitarr.toml (or $$WAITARR_CONFIG)
	@$(PY) waitarr run

format: ## qa: Format and fix Python files
	@$(PY) ruff check --fix $(PY_PATHS)
	@$(PY) black $(PY_PATHS)

lint: ## qa: Check style and types without modifying files
	@$(PY) ruff check --no-fix $(PY_PATHS)
	@$(PY) black --check $(PY_PATHS)
	@$(PY) pyright

test: ## qa: Run the hermetic test suite (no Docker, no network)
	@$(PY) pytest -m "not docker and not image and not network and not live"

test-live: sync ## qa: Read-only tests against the real Jellyfin of WAITARR_LIVE_JELLYFIN_URL (never in CI)
	@$(PY) pytest -m live tests/integration -rs

test-docker: sync ## qa: Run the integration suite against a disposable qBittorrent container (needs Docker)
	@$(PY) pytest -m docker tests/integration; \
	status=$$?; \
	leaked=$$(docker ps -aq --filter "label=waitarr.test" | wc -l); \
	if [ "$$leaked" -ne 0 ]; then \
		printf '[LEAK] %s test container(s) left behind\n' "$$leaked" >&2; \
		exit 1; \
	fi; \
	exit $$status

check-version: ## qa: Verify pyproject.toml and the Release Please manifest agree
	@python3 scripts/check_version_sync.py

check-docs: ## qa: Verify every Markdown link and repo-anchored path resolves
	@python3 scripts/check_doc_links.py

check-ai: ## qa: Enforce commit provenance, no generated artefacts, house style
	@python3 scripts/check_ai_hygiene.py

# Prefer a local gitleaks; fall back to the official image. Neither is an
# error, never a skip: a scanner that does nothing reports "clean".
GITLEAKS_IMAGE := zricethezav/gitleaks:v8.24.3
GITLEAKS_SCOPE ?= dir
GITLEAKS_SOURCE_FLAGS = $(if $(filter dir,$(GITLEAKS_SCOPE)),--no-git,)

secrets: ## qa: Scan for committed credentials with gitleaks (GITLEAKS_SCOPE=dir|git)
	@case "$(GITLEAKS_SCOPE)" in dir|git) ;; \
		*) printf "Unknown GITLEAKS_SCOPE '%s'. Use 'dir' or 'git'.\n" "$(GITLEAKS_SCOPE)" >&2; exit 2 ;; \
	esac
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --source . $(GITLEAKS_SOURCE_FLAGS) \
			-c .gitleaks.toml --no-banner --redact; \
	elif command -v docker >/dev/null 2>&1; then \
		docker run --rm -v "$(CURDIR):/repo" -w /repo $(GITLEAKS_IMAGE) \
			detect --source . $(GITLEAKS_SOURCE_FLAGS) \
			-c /repo/.gitleaks.toml --no-banner --redact; \
	else \
		printf 'MISSING: gitleaks. Install it or provide Docker.\n' >&2; exit 1; \
	fi

deps-audit: sync ## qa: Audit dependencies for known vulnerabilities with pip-audit (needs network)
	@$(PY) pip-audit

# osv-scanner: the local binary when installed, else its official image.
# A Python vulnerability fails; a base-image OS one is only listed
# (scripts/osv_gate.py says why).
OSV_IMAGE := ghcr.io/google/osv-scanner:v2.7.0@sha256:4f3b7e2c64b9d38a5febc5a7e4a3dfef1d1362f726dea7a2ef4762b46469fcd0
OSV_TMP := .osv

vulns: image ## qa: Scan poetry.lock and the built image with osv-scanner (needs Docker and the network)
	@rm -rf $(OSV_TMP) && mkdir -p $(OSV_TMP)
	@docker save $(IMAGE) -o $(OSV_TMP)/image.tar
	@if command -v osv-scanner >/dev/null 2>&1; then \
		osv-scanner scan source --lockfile poetry.lock --format json --verbosity error > $(OSV_TMP)/lock.json || true; \
		osv-scanner scan image --archive $(OSV_TMP)/image.tar --format json --verbosity error > $(OSV_TMP)/image.json || true; \
	else \
		docker run --rm -v "$(CURDIR):/src:ro" -w /src $(OSV_IMAGE) \
			scan source --lockfile poetry.lock --format json --verbosity error > $(OSV_TMP)/lock.json || true; \
		docker run --rm -v "$(CURDIR)/$(OSV_TMP):/scan:ro" $(OSV_IMAGE) \
			scan image --archive /scan/image.tar --format json --verbosity error > $(OSV_TMP)/image.json || true; \
	fi
	@status=0; \
	python3 scripts/osv_gate.py --label poetry.lock $(OSV_TMP)/lock.json || status=1; \
	python3 scripts/osv_gate.py --label "image $(IMAGE)" $(OSV_TMP)/image.json || status=1; \
	rm -rf $(OSV_TMP); exit $$status

check-fast: sync ## qa: Fast checkpoint: lint, types and hermetic tests
	@$(MAKE) lint
	@$(MAKE) test

check: sync lint test check-version check-docs check-ai ## qa: Run every required check (no Docker) -- the push/PR gate

build: sync ## dev: Build the wheel and sdist into dist/
	@rm -rf dist
	@poetry build

check-dist: build ## qa: Validate the built artefacts and smoke-test the installed entrypoint (needs network)
	@$(PY) twine check --strict dist/*
	@$(PY) pytest -m network tests/test_distribution.py

social-preview: ## dev: Render docs/assets/social-preview.png from the logo (needs ImageMagick with Pango)
	@bash scripts/render_social_preview.sh

image: ## use: Build the container image for this machine ($(IMAGE))
	@docker build \
		--build-arg VERSION="$$(poetry version -s)" \
		--build-arg REVISION="$$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
		-t $(IMAGE) .

image-multiarch: ## qa: Build the image for amd64 and arm64 without pushing (needs buildx + QEMU)
	@docker buildx build --platform $(PLATFORMS) \
		--build-arg VERSION="$$(poetry version -s)" -t $(IMAGE) .

check-image: sync image ## qa: Build the image and run the end-to-end scenario against disposable containers (needs Docker)
	@WAITARR_TEST_IMAGE=$(IMAGE) $(PY) pytest -m image tests/integration

ci-entrypoint: ## qa: Verify the CLI entrypoint responds
	@$(PY) waitarr --version
	@$(PY) waitarr --help >/dev/null

ci: ## qa: What CI runs: install, check, entrypoint
	@poetry install --no-interaction --no-ansi
	@$(MAKE) check
	@$(MAKE) ci-entrypoint

clean: ## dev: Remove generated, reproducible artefacts (never .venv, .git or config)
	@find $(PY_PATHS) -type d -name "__pycache__" -exec rm -rf {} +
	@rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist .sync-stamp
	@printf 'Cleaned.\n'
