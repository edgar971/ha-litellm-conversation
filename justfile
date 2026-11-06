# ha-litellm-conversation — one task runner for every gate. `just --list` shows the recipes.
# CI (.github/workflows/ci.yml) runs these same gates, so nothing is checked only locally.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Python environment holding pytest and ruff. Override for a one-off run:
#   VENV=/path/to/venv just check
venv := env_var_or_default("VENV", ".venv")

# Interpreter `just setup` builds the venv with. Override with PYTHON=/path/to/python.
python := env_var_or_default("PYTHON", "python3.14")

# `just` alone lists the recipes
[private]
default:
    @just --list

# Create the venv and install the dev dependencies (needs Python 3.14)
setup:
    {{python}} -m venv {{venv}}
    {{venv}}/bin/pip install --upgrade pip
    {{venv}}/bin/pip install -e ".[dev]"

# Every gate CI runs: lint, format check, tests. Run this before every commit.
check: lint format-check test

# Ruff lint
lint:
    {{venv}}/bin/ruff check . --config ruff.toml

# The formatter as a read-only check (the CI gate; `just format` applies instead)
[private]
format-check:
    {{venv}}/bin/ruff format --check . --config ruff.toml

# Apply the formatter and the safe lint fixes
format:
    {{venv}}/bin/ruff format . --config ruff.toml
    {{venv}}/bin/ruff check . --config ruff.toml --fix

# The pytest suite (pytest-homeassistant-custom-component)
test:
    {{venv}}/bin/python -m pytest tests/ -q

# Set up the local HA dev environment (writes config/, links custom_components)
dev:
    ./scripts/develop

# Render changelog sections with git-cliff (cliff.toml). Prints to stdout —
# paste the rendered section into CHANGELOG.md when cutting a release.
# Examples: `just changelog` (unreleased), `just changelog v1.8.0..HEAD`.
changelog range="":
    #!/usr/bin/env bash
    set -euo pipefail
    args="{{ if range == "" { "--unreleased" } else { range } }}"
    if command -v git-cliff >/dev/null; then
        git-cliff $args
    elif command -v uvx >/dev/null; then
        uvx --from git-cliff git-cliff $args
    else
        echo "git-cliff not found. Install it ('brew install git-cliff') or install uv," >&2
        echo "then re-run: just changelog {{ if range == "" { "--unreleased" } else { range } }}" >&2
        exit 1
    fi

