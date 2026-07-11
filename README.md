# LiteLLM Conversation for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/release/edgar971/ha-litellm-conversation.svg)](https://github.com/edgar971/ha-litellm-conversation/releases)
[![License](https://img.shields.io/github/license/edgar971/ha-litellm-conversation.svg)](LICENSE)

A Home Assistant custom integration that connects any [LiteLLM proxy](https://docs.litellm.ai/) to Home Assistant as a **Conversation agent** and **AI Task provider** — giving you access to hundreds of LLM models (Bedrock Claude, OpenAI GPT-4, Anthropic Claude, Ollama, Azure OpenAI, and more) without being locked into a single provider.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🗣️ **Conversation Agent** | Use any LiteLLM-backed model as your HA voice/chat assistant |
| 🌊 **Streaming Responses** | Real-time streamed replies for a snappy assistant experience |
| 🔧 **Tool / Function Calling** | Let the LLM control HA devices via the HA LLM API (lights, locks, scenes, etc.) |
| 📊 **AI Task: generate_data** | Structured output via the `ai_task` platform — parse, classify, or generate JSON |
| 🔑 **Custom System Prompts** | Per-subentry system prompt templates with HA template variables |
| ⚙️ **Full Model Control** | Configure model, temperature, top-p, and max tokens per subentry |
| 🌐 **Any Model LiteLLM Supports** | One proxy, unlimited backends: Bedrock, OpenAI, Anthropic, Ollama, Mistral, Gemini, and more |

---

## 🚀 Installation

### Prerequisites

- Home Assistant **2025.7.0** or later (uses config subentries and the modern ChatLog LLM APIs)
- A running [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start) with at least one model configured

### Via HACS (Recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Click the three-dot menu → **Custom repositories**.
3. Add the URL `https://github.com/edgar971/ha-litellm-conversation` with category **Integration**.
4. Search for **LiteLLM Conversation** and click **Download**.
5. **Restart Home Assistant.**

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/edgar971/ha-litellm-conversation/releases).
2. Extract and copy the `custom_components/litellm_conversation` folder into your HA configuration directory under `config/custom_components/`.
3. **Restart Home Assistant.**

---

## ⚙️ Configuration

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

### Step 4 — Assign to Voice Assistant

1. Go to **Settings** → **Voice Assistants**.
2. Edit your assistant or create a new one.
3. Under **Conversation agent**, select **LiteLLM Conversation**.

---

## 🤖 Supported Model Providers

LiteLLM acts as a unified proxy. Configure your models in `litellm_config.yaml` and point this integration at your proxy:

| Provider | Example Model String |
|----------|---------------------|
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Anthropic (direct) | `claude-opus-4-5`, `claude-sonnet-4-5` |
| AWS Bedrock | `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Azure OpenAI | `azure/gpt-4o` |
| Ollama (local) | `ollama/llama3.2`, `ollama/mistral` |
| Google Gemini | `gemini/gemini-1.5-pro` |
| Mistral | `mistral/mistral-large-latest` |

See the full list at [docs.litellm.ai/providers](https://docs.litellm.ai/docs/providers).

---

## 🛠️ Troubleshooting

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

## 🎨 Brand Assets

Brand icons/logos for this integration are not yet submitted to the official [Home Assistant Brands repository](https://github.com/home-assistant/brands). Contributions welcome — see their [contributing guide](https://github.com/home-assistant/brands#contributing) for the required formats.

---

## 👩‍💻 Developer Guide

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
│       ├── ai_task.py           # AI Task platform (generate_data)
│       ├── config_flow.py       # Config + subentry UI flows
│       ├── const.py             # Constants, defaults
│       ├── conversation.py      # Conversation agent platform
│       ├── entity.py            # Base entity (shared OpenAI client)
│       ├── manifest.json        # Integration metadata
│       ├── strings.json         # UI strings (English)
│       └── translations/        # i18n translations
├── tests/
│   ├── conftest.py              # Pytest fixtures
│   └── test_const.py            # Unit tests
├── .devcontainer/
│   └── devcontainer.json        # VS Code dev container config
├── scripts/
│   └── develop                  # Post-create setup script
├── .github/
│   └── workflows/
│       └── ci.yml               # CI: ruff + pytest
├── pyproject.toml               # Package metadata & test config
├── ruff.toml                    # Ruff linter config
└── hacs.json                    # HACS metadata
```

### Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

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

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
