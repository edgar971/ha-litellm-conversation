# Contributing to LiteLLM Conversation

Thank you for your interest in contributing! This document explains how to set up your development environment, follow our code style, and submit changes.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Bugs](#reporting-bugs)

---

## Code of Conduct

Please be respectful and constructive. We follow the [Home Assistant Community Guidelines](https://www.home-assistant.io/blog/2016/01/09/ha-101-development/).

---

## Getting Started

### Fork and Clone

1. Fork the repo on GitHub: [edgar971/ha-litellm-conversation](https://github.com/edgar971/ha-litellm-conversation)
2. Clone your fork:

   ```bash
   git clone https://github.com/<your-username>/ha-litellm-conversation
   cd ha-litellm-conversation
   ```

3. Add the upstream remote:

   ```bash
   git remote add upstream https://github.com/edgar971/ha-litellm-conversation
   ```

---

## Development Environment

This project is designed to run inside a **VS Code Dev Container** using the official HA integration blueprint image.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [VS Code](https://code.visualstudio.com/)
- [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

### Setup Steps

1. Open the cloned repo in VS Code:

   ```bash
   code .
   ```

2. When prompted, click **"Reopen in Container"** (or use the command palette: `Dev Containers: Reopen in Container`).

3. The container will automatically run `scripts/develop`, which:
   - Creates a `config/` directory
   - Writes a minimal `configuration.yaml` with debug logging enabled for this integration
   - Symlinks `custom_components/` into `config/custom_components/`

4. Start Home Assistant:

   ```bash
   hass -c config/
   ```

5. Open [http://localhost:8123](http://localhost:8123) and complete onboarding.

> **Tip:** The `config/` directory is gitignored. Your local HA instance data won't be committed.

---

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, configured via `ruff.toml`.

We follow [Home Assistant's development guidelines](https://developers.home-assistant.io/docs/development_guidelines) where applicable:

- Type hints on all public functions and methods
- `from __future__ import annotations` at the top of every module
- Use `LOGGER = logging.getLogger(__package__)` — no `print()` statements
- Async-first: use `async def` and `await` for all I/O operations
- Config entries use subentries — avoid top-level YAML configuration

### Running Linting

```bash
# Check for issues
ruff check . --config ruff.toml

# Auto-fix safe violations
ruff check . --config ruff.toml --fix

# Format
ruff format . --config ruff.toml
```

CI will fail if ruff reports any errors. Please fix all lint issues before opening a PR.

---

## Running Tests

```bash
# Run all tests
pytest tests/

# Verbose output
pytest tests/ -v

# With coverage report
pytest tests/ --cov=custom_components/litellm_conversation --cov-report=term-missing
```

When adding new features, please add or update tests in `tests/`. Integration tests should use the `hass` fixture from `homeassistant.core` where possible.

---

## Submitting a Pull Request

### Branching Convention

Create a descriptive branch from `main`:

```bash
git checkout -b fix/tool-calling-timeout
git checkout -b feat/add-streaming-indicator
git checkout -b docs/improve-readme
```

Prefix conventions:
- `feat/` — new feature
- `fix/` — bug fix
- `docs/` — documentation only
- `chore/` — maintenance (deps, CI, config)
- `refactor/` — code restructuring without behavior change

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat: add support for structured output in ai_task platform
fix: handle timeout when fetching model list
docs: add troubleshooting section to README
chore: bump openai requirement to >=1.60.0
```

### PR Checklist

Before opening your PR, make sure:

- [ ] Ruff passes with no errors: `ruff check . --config ruff.toml`
- [ ] All tests pass: `pytest tests/`
- [ ] New features include tests
- [ ] `manifest.json` version is bumped if the change warrants a release
- [ ] Strings/translations updated if UI text changed (`strings.json` + `translations/en.json`)
- [ ] The PR description explains **what** changed and **why**

### PR Process

1. Push your branch and open a PR against `main`.
2. CI (ruff + pytest) must pass.
3. Address any review feedback.
4. A maintainer will merge once approved.

---

## Reporting Bugs

Use the [GitHub Issues](https://github.com/edgar971/ha-litellm-conversation/issues) tracker. Include:

- Home Assistant version
- Integration version
- LiteLLM proxy version
- Relevant log output (enable debug logging first — see README)
- Steps to reproduce

---

## Questions?

Open a [GitHub Discussion](https://github.com/edgar971/ha-litellm-conversation/discussions) for questions, ideas, or general feedback.
