PYTHON ?= python3
PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
BIN_DIR ?= $(HOME)/.local/bin
USER_BIN := $(shell "$(PYTHON)" -c "import sysconfig; print(sysconfig.get_path('scripts', scheme=sysconfig.get_preferred_scheme('user')))")

.PHONY: install
install:
	@rm -rf "$(PROJECT_ROOT)/build"
	@log=$$(mktemp "$${TMPDIR:-/tmp}/dots-install.XXXXXX"); \
	if "$(PYTHON)" -m pip install --quiet --user --break-system-packages "$(PROJECT_ROOT)" >"$$log" 2>&1; then \
		rm -f "$$log"; \
	else \
		printf 'Install failed. Details: %s\n' "$$log" >&2; exit 1; \
	fi
	@mkdir -p "$(BIN_DIR)"
	@if [ "$(USER_BIN)" != "$(BIN_DIR)" ]; then ln -sf "$(USER_BIN)/dots" "$(BIN_DIR)/dots"; fi
	@printf 'Installed dots.\n'
