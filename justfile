# ha-litellm-conversation — one task runner for every gate. `just --list` shows the recipes.
# CI (.github/workflows/ci.yml) runs these same gates, so nothing is checked only locally.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Python environment holding pytest and ruff. Override for a one-off run:
#   VENV=/path/to/venv just check
venv := env_var_or_default("VENV", ".venv")

# `just` alone lists the recipes
[private]
default:
    @just --list

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
