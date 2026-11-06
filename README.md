# LiteLLM Conversation for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/release/edgar971/ha-litellm-conversation.svg)](https://github.com/edgar971/ha-litellm-conversation/releases)
[![License](https://img.shields.io/github/license/edgar971/ha-litellm-conversation.svg)](LICENSE)

Connects any [LiteLLM proxy](https://docs.litellm.ai/) to Home Assistant as a conversation agent and AI Task provider. Whatever models your proxy serves — Bedrock, OpenAI, Anthropic, Ollama, Azure OpenAI — become available to Assist, `ai_task.generate_data`, STT/TTS pipelines, and usage sensors.

> [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=litellm_conversation)

---

## Difference from the built-in `litellm` integration

Home Assistant core ships its own [`litellm`](https://www.home-assistant.io/integrations/litellm/) integration (Bronze quality scale, conversation + STT only). This integration uses a **separate domain** (`litellm_conversation`) so both can coexist, and adds:

- **AI Task provider** (`generate_data` with structured/vision output, `generate_image`)
- **Streaming responses**, per-subentry model/temperature/top-p/max-tokens control
- **Extended tools**: any-service calls, history, URL fetch, camera vision, calendars, to-do lists
- **TTS platform** and **spend/cost sensors** per model
- Full model-dropdown control against your own proxy

If you only need a basic conversation agent from a LiteLLM proxy, the built-in integration may be enough. If you want AI Tasks, streaming, tool-heavy Assist setups, or cost visibility, use this one.

---

## Features

| Feature | Description |
|---------|-------------|
| **Conversation Agent** | Use any LiteLLM-backed model as your HA voice/chat assistant |
| **Streaming Responses** | Replies stream token-by-token into the Assist bubble |
| **Tool / Function Calling** | Let the LLM control HA devices via the HA LLM API (lights, locks, scenes, etc.) |
| **Extended Tools** | Optional power tools: any-service calls, history, URL fetch, camera vision, calendars, to-do lists |
| **Vision** | Image attachments for AI Tasks (camera snapshots → structured answers) and an `analyze_camera` voice tool |
| **AI Task: generate_data** | Structured output via the `ai_task` platform — parse, classify, or generate JSON |
| **AI Task: generate_image** | Image generation via LiteLLM's `/v1/images/generations` — set an *Image model* per AI Task subentry (optional size/quality passthrough; any image-capable proxy deployment: Bedrock SD, OpenAI, Vertex) |
| **Custom System Prompts** | Per-subentry system prompt templates with HA template variables |
| **Full Model Control** | Configure model, temperature, top-p, and max tokens per subentry |
| **Web Search** | Optional native web search via LiteLLM's `web_search_options` passthrough |
| **Speech-to-Text** | Whisper-compatible STT platform for voice assistant pipelines |
| **Text-to-Speech** | OpenAI-compatible TTS platform with voice selection |
| **Usage Sensors** | Daily request/token counters exposed as diagnostic sensors |
| **Proxy Spend & Budget Sensors** | Proxy-reported USD spend + budget utilization %, polled from LiteLLM `/key/info` (virtual key, no admin) |
| **Request Tagging** | Every chat request tagged (`metadata.tags`) so LiteLLM spend logs / Grafana can slice Home Assistant traffic |
| **Guardrails** | Pass LiteLLM proxy guardrails (PII masking, content filtering) per agent |
| **Any Model LiteLLM Supports** | Whatever your proxy is configured with — the integration adds no model allowlist |

---

## Use with MCP Servers

Home Assistant's [MCP integration](https://www.home-assistant.io/integrations/mcp/) exposes tools from any MCP server (memory, web search, RAG, etc.) to conversation agents through the HA LLM API framework. This integration supports that out of the box:

1. Set up the **Model Context Protocol** integration in HA and point it at your MCP server(s).
2. In your LiteLLM conversation agent's options, select the MCP-provided API under **Home Assistant LLM API** (alongside or instead of the built-in Assist API).
3. The MCP server's tools are now available to your agent automatically — no extra configuration needed here.

---

## Extended Tools (power users)

Selecting **LiteLLM Extended Tools** as the agent's LLM API (instead of the default Assist API) gives the model everything Assist provides **plus** six power tools:

| Tool | What it does |
| :--- | :--- |
| `call_service` | Call any HA service (`light.turn_on`, `script.movie_night`, ...) with a full payload |
| `get_history` | Query recorder state history for an entity (up to 7 days) |
| `fetch_url` | HTTP GET a public URL and return the body (100 KB cap) — external APIs like weather or transit |
| `analyze_camera` | Snapshot a camera and answer a question about the image ("Is there a package by the door?") — runs a nested vision call through your LiteLLM proxy using the conversation agent's model |
| `get_calendar_events` | Read upcoming events from a calendar entity (up to 30 days ahead) |
| `add_todo_item` | Add an item to a to-do/shopping list ("add milk to the shopping list") |

### Security notes

These tools intentionally give the model more reach than the Assist API. Built-in guardrails:

- `call_service` refuses system domains: `homeassistant`, `hassio`, `shell_command`, `python_script`, `recorder` — a prompt-injected model cannot restart HA or run arbitrary code.
- `fetch_url` only accepts `http`/`https` and **blocks URLs resolving to private, loopback, or link-local addresses** (SSRF guard) — the model cannot probe your LAN, the Supervisor API, or your router.
- `analyze_camera`, `get_calendar_events`, and `add_todo_item` only work with entities **exposed to Assist** — a prompt-injected model cannot look at cameras or lists you chose not to expose.
- `analyze_camera` makes an extra model call per use (the vision request); its token usage is counted by the usage sensors.
- `call_service` is still powerful: it can operate locks, garage doors, and alarm panels if those services exist. Only enable Extended Tools on agents you trust with device control, and keep sensitive entities unexposed where possible.

---

## Installation

### Prerequisites

- Home Assistant **2025.7.0** or later (uses config subentries and the modern ChatLog LLM APIs)
- A running [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start) with at least one model configured

### Via Marketplace / HACS (Recommended)

**Home Assistant 2026.11 or newer** ships [Marketplace](https://contributors.home-assistant.io/marketplace/) built in (Settings → Marketplace — HACS is no longer installed separately):

1. Open **Settings → Marketplace**.
2. Click **→ Add custom repository** and add `https://github.com/edgar971/ha-litellm-conversation` with category **Integration**.
3. Search for **LiteLLM Conversation** and click **Download**.
4. **Restart Home Assistant.**

**Home Assistant 2025.x / 2026.10 or older** (HACS custom integration): open **HACS**, three-dot menu → **Custom repositories**, add the same URL with category **Integration**, then download and restart.

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/edgar971/ha-litellm-conversation/releases).
2. Extract and copy the `custom_components/litellm_conversation` folder into your HA configuration directory under `config/custom_components/`.
3. **Restart Home Assistant.**

### Removal

1. Go to **Settings → Devices & Services → LiteLLM Conversation**, open the three-dot menu on the entry, and select **Delete**.
2. If installed via HACS: open HACS, find **LiteLLM Conversation**, three-dot menu → **Remove**. If installed manually: delete `config/custom_components/litellm_conversation/`.
3. **Restart Home Assistant.** All entities, subentries, and usage sensors are removed with the config entry; the integration stores no other data.

---

## Configuration

### Step 1 — Add the Integration

1. Go to **Settings** → **Devices & Services** → **+ Add Integration**.
2. Search for **LiteLLM Conversation** and select it.

### Step 2 — Enter Connection Details

| Field | Example | Notes |
|-------|---------|-------|
| **LiteLLM Base URL** | `http://192.168.1.100:4000` | Your LiteLLM proxy URL (without `/v1`) |
| **API Key** | `sk-my-key` | Your LiteLLM proxy master key |

The integration will automatically fetch the model list from your proxy.

### Step 3 — Configure Subentries

Two subentries are created automatically:

#### Conversation Subentry

| Option | Default | Description |
|--------|---------|-------------|
| **Model** | First available | Model to use for conversation |
| **System Prompt** | (empty) | Jinja2 template for the system prompt |
| **Temperature** | `1.0` | Sampling temperature (0–2) |
| **Max Tokens** | `4096` | Maximum response tokens |
| **Top P** | `1.0` | Nucleus sampling parameter |
| **HA LLM API** | `No control` | Enable device control via HA's LLM API |

#### AI Task (generate_data) Subentry

Provides the `ai_task.generate_data` action for structured output. Supports the same model/temperature/max-token options as conversation.

##### Vision: image attachments

AI Task entities accept **image attachments** — including live camera snapshots via `media-source://camera/...`. The image is sent to your model through the LiteLLM proxy (vision-capable model required, e.g. Claude on Bedrock):

```yaml
action: ai_task.generate_data
data:
  entity_id: ai_task.litellm_ai_task
  task_name: porch check
  instructions: Is there a package on the porch? Answer yes or no with a short reason.
  attachments:
    media_content_id: media-source://camera/camera.driveway
    media_content_type: image/jpeg
  structure:
    package:
      selector:
        boolean:
    reason:
      selector:
        text:
```

Only image attachments are supported (PDFs are rejected — Bedrock's Chat Completions path does not reliably accept them).

### Step 4 — Assign to Voice Assistant

1. Go to **Settings** → **Voice Assistants**.
2. Edit your assistant or create a new one.
3. Under **Conversation agent**, select **LiteLLM Conversation**.

---

## Supported Model Providers

LiteLLM acts as a unified proxy. Configure your models in `litellm_config.yaml` and point this integration at your proxy:

| Provider | Example Model String |
|----------|---------------------|
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Anthropic (direct) | `claude-opus-4-5`, `claude-sonnet-4-5` |
| AWS Bedrock | `bedrock/us.anthropic.claude-sonnet-4-5` |
| Azure OpenAI | `azure/gpt-4o` |
| Ollama (local) | `ollama/llama3.2`, `ollama/mistral` |
| Google Gemini | `gemini/gemini-1.5-pro` |
| Mistral | `mistral/mistral-large-latest` |

See the full list at [docs.litellm.ai/providers](https://docs.litellm.ai/docs/providers).

---

## Troubleshooting

### Integration can't connect to LiteLLM proxy

- Verify your proxy is running: `curl http://<proxy-url>/health`
- Make sure HA can reach the proxy (same network, no firewall blocking)
- Check that the URL does **not** end in `/v1` — the integration appends it automatically

### "invalid_auth" error

- Double-check your LiteLLM master key in the proxy config
- Try `curl http://<proxy-url>/v1/models -H "Authorization: Bearer <key>"`

### No models listed in dropdown

- Ensure models are configured in your LiteLLM proxy `litellm_config.yaml`
- Restart the proxy and retry configuration

### Tool calling not working

- Make sure you selected an **HA LLM API** in the conversation subentry (not "No control")
- Check that the selected model supports function calling

### Debug logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.litellm_conversation: debug
```

Then check **Settings** → **System** → **Logs** for detailed output.

---

## Developer Guide

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [VS Code](https://code.visualstudio.com/)
- [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

### Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/edgar971/ha-litellm-conversation
cd ha-litellm-conversation

# 2. Open in VS Code
code .
```

3. VS Code will prompt **"Reopen in Container"** — click it (or run `Dev Containers: Reopen in Container` from the command palette).
4. The container will build and run `scripts/develop` automatically, which:
   - Creates a `config/` directory
   - Writes a minimal `configuration.yaml` with debug logging for this integration
   - Symlinks `custom_components/` into `config/custom_components/`
5. Start Home Assistant:
   ```bash
   hass -c config/
   ```
6. Open [http://localhost:8123](http://localhost:8123) and complete onboarding.

### Project Structure

```
ha-litellm-conversation/
├── custom_components/
│   └── litellm_conversation/
│       ├── __init__.py          # Integration setup, config entry load/unload
│       ├── ai_task.py           # AI Task platform (generate_data + attachments)
│       ├── config_flow.py       # Config + subentry UI flows
│       ├── const.py             # Constants, defaults
│       ├── conversation.py      # Conversation agent platform
│       ├── diagnostics.py       # Redacted diagnostics export
│       ├── entity.py            # Base entity, request building, streaming, attachments
│       ├── extended_tools.py    # Extended Tools LLM API (6 tools)
│       ├── schemas.py           # Subentry form schemas
│       ├── sensor.py            # Daily usage counters + proxy spend/budget sensors
│       ├── stt.py               # Speech-to-text platform
│       ├── tts.py               # Text-to-speech platform
│       ├── util.py              # Shared helpers
│       ├── manifest.json        # Integration metadata
│       ├── strings.json         # UI strings (English)
│       └── translations/        # i18n translations
├── tests/                       # Pytest suite (pytest-homeassistant-custom-component)
├── .devcontainer/               # VS Code dev container config
├── .github/workflows/ci.yml    # CI: ruff + pytest + hassfest + HACS validation
├── justfile                     # Task runner mirroring the CI gates (just --list)
├── pyproject.toml               # Package metadata & test config
├── ruff.toml                    # Ruff linter config
└── hacs.json                    # HACS metadata
```

### Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. All local gates are wrapped in the [justfile](justfile) — run `just --list` for the recipes, `just check` for everything CI runs.

```bash
# Check for lint errors
ruff check . --config ruff.toml

# Auto-fix safe issues
ruff check . --config ruff.toml --fix

# Format code
ruff format . --config ruff.toml
```

### Tests

```bash
pytest tests/

# With verbose output
pytest tests/ -v

# With coverage
pytest tests/ --cov=custom_components/litellm_conversation
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide, including branching conventions, PR process, and code style expectations.

More docs: [LiteLLM/Bedrock compatibility notes](docs/litellm-compat.md) · [ADRs](docs/adr/) · [future ideas](https://github.com/edgar971/ha-litellm-conversation/issues/12).

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
