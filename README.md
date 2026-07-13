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
| 🛠️ **Extended Tools** | Optional power tools: any-service calls, history, URL fetch, camera vision, calendars, to-do lists |
| 🧠 **Long-Term Memory** | Durable facts persist across conversations — managed from HA's To-do panel |
| 💤 **Dreaming** | Background memory consolidation: learn from conversations automatically, on your schedule |
| 📷 **Vision** | Image attachments for AI Tasks (camera snapshots → structured answers) and an `analyze_camera` voice tool |
| 📊 **AI Task: generate_data** | Structured output via the `ai_task` platform — parse, classify, or generate JSON |
| 🔑 **Custom System Prompts** | Per-subentry system prompt templates with HA template variables |
| ⚙️ **Full Model Control** | Configure model, temperature, top-p, and max tokens per subentry |
| 🔎 **Web Search** | Optional native web search via LiteLLM's `web_search_options` passthrough |
| 🎤 **Speech-to-Text** | Whisper-compatible STT platform for voice assistant pipelines |
| 🔊 **Text-to-Speech** | OpenAI-compatible TTS platform with voice selection |
| 📈 **Usage Sensors** | Daily request/token counters exposed as diagnostic sensors |
| 🛡️ **Guardrails** | Pass LiteLLM proxy guardrails (PII masking, content filtering) per agent |
| 🌐 **Any Model LiteLLM Supports** | One proxy, unlimited backends: Bedrock, OpenAI, Anthropic, Ollama, Mistral, Gemini, and more |

---

## 🔌 Use with MCP Servers

Home Assistant's [MCP integration](https://www.home-assistant.io/integrations/mcp/) exposes tools from any MCP server (memory, web search, RAG, etc.) to conversation agents through the HA LLM API framework. This integration supports that out of the box:

1. Set up the **Model Context Protocol** integration in HA and point it at your MCP server(s).
2. In your LiteLLM conversation agent's options, select the MCP-provided API under **Home Assistant LLM API** (alongside or instead of the built-in Assist API).
3. The MCP server's tools are now available to your agent automatically — no extra configuration needed here.

---

## 🔧 Extended Tools (power users)

Selecting **LiteLLM Extended Tools** as the agent's LLM API (instead of the default Assist API) gives the model everything Assist provides **plus** six power tools:

| Tool | What it does |
| :--- | :--- |
| `call_service` | Call any HA service (`light.turn_on`, `script.movie_night`, ...) with a full payload |
| `get_history` | Query recorder state history for an entity (up to 7 days) |
| `fetch_url` | HTTP GET a public URL and return the body (100 KB cap) — external APIs like weather or transit |
| `analyze_camera` | Snapshot a camera and answer a question about the image ("Is there a package by the door?") — runs a nested vision call through your LiteLLM proxy using the conversation agent's model |
| `get_calendar_events` | Read upcoming events from a calendar entity (up to 30 days ahead) |
| `add_todo_item` | Add an item to a to-do/shopping list ("add milk to the shopping list") |
| `remember` / `forget` / `list_memories` | Long-term memory: durable facts that persist across conversations (see below) |

### ⚠️ Security notes

These tools intentionally give the model more reach than the Assist API. Built-in guardrails:

- `call_service` refuses system domains: `homeassistant`, `hassio`, `shell_command`, `python_script`, `recorder` — a prompt-injected model cannot restart HA or run arbitrary code.
- `fetch_url` only accepts `http`/`https` and **blocks URLs resolving to private, loopback, or link-local addresses** (SSRF guard) — the model cannot probe your LAN, the Supervisor API, or your router.
- `analyze_camera`, `get_calendar_events`, and `add_todo_item` only work with entities **exposed to Assist** — a prompt-injected model cannot look at cameras or lists you chose not to expose.
- `analyze_camera` makes an extra model call per use (the vision request); its token usage is counted by the usage sensors.
- Memories are injected as **reference facts, never instructions**, capped at 50 entries × 300 chars — a prompt-injected "memory" can't become a standing order, and memory growth can't silently inflate token spend.
- `call_service` is still powerful: it can operate locks, garage doors, and alarm panels if those services exist. Only enable Extended Tools on agents you trust with device control, and keep sensitive entities unexposed where possible.

---

## 🧠 Long-Term Memory

Agents using the Extended Tools API get **persistent memory across conversations**. Say *"remember that the water shutoff is behind the basement panel"* — weeks later, in a fresh conversation, the agent knows.

**How it works:**

- The model calls `remember` when you state a durable fact; stored memories are injected into every conversation's system prompt (max 50 memories, 300 chars each)
- Storage is a local JSON file in HA's `.storage/` — nothing leaves your box
- Say *"what do you remember?"* (`list_memories`) or *"forget the thing about the shutoff"* (`forget`)

**Manage memories in the UI:** the integration creates a **`todo.*_memories`** entity — open HA's built-in **To-do lists** panel to review, edit, add, or delete everything the assistant knows. Deleting or checking off an item forgets it. Add a standard todo-list card to any dashboard to keep memories visible.

**Automation-driven memories** via services:

```yaml
# Example: remember appliance service visits automatically
automation:
  - alias: "Remember furnace service"
    triggers:
      - trigger: calendar
        entity_id: calendar.family
        event: end
    conditions: "{{ 'furnace' in trigger.calendar_event.summary | lower }}"
    actions:
      - action: litellm_conversation.remember
        data:
          text: "Furnace last serviced {{ now().strftime('%B %Y') }}"
```

`litellm_conversation.forget` removes memories matching a text fragment. Both services return response data (`remembered`/`removed`).

### 💤 Dreaming — background memory consolidation

Beyond the explicit `remember` tool, the integration can **learn from conversations automatically**. A "dream" is one LLM call that analyzes recent conversation transcripts (and optionally household activity) against the current memory list, then adds, updates, merges, or deletes memories — the same architecture ChatGPT uses (a hot-path memory tool + background consolidation).

**How it fits HA:** the integration provides the capability; *your automations* provide the schedule. There is no built-in timer.

- **`litellm_conversation.dream`** service — fields: `model` (optional override; a cheap model is recommended), `include_activity` (also analyze logbook events: automations, presence, locks), `dry_run` (return proposed operations *without* applying — build review flows). Returns `added/updated/deleted/operations/tokens`.
- **`switch.*_transcript_capture`** — dreams need material, so conversation exchanges (your text + the reply, never tool internals) are kept in a local rolling buffer (7 days / 200 exchanges, in `.storage/`). The switch pauses capture; `litellm_conversation.clear_transcripts` wipes the buffer. **HA itself never stores conversations — this buffer is the only copy, and it never leaves your box.**
- **`sensor.*_last_dream`** — timestamp + summary attributes (added/updated/deleted/tokens).
- **`litellm_conversation_dream_completed`** event fires on the bus with the summary — drive notifications or chained automations.

**Quick start:** import the bundled blueprint for a nightly dream with an optional "what I learned" notification:

[![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fedgar971%2Fha-litellm-conversation%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnightly_dreaming.yaml)

Or by hand:

```yaml
automation:
  - alias: "Nightly dreaming"
    triggers:
      - trigger: time
        at: "03:00:00"
    actions:
      - action: litellm_conversation.dream
        data:
          include_activity: true
          model: bedrock-claude-4-5-haiku  # cheap model for nightly runs
```

**Cautious mode (review before applying):** call with `dry_run: true`, send the proposed `operations` as an actionable notification, and only call the real dream (or targeted `remember`/`forget`) after approval.

### 🖥️ Memory dashboard (no custom cards needed)

Everything composes from standard Lovelace cards:

```yaml
type: vertical-stack
cards:
  - type: todo-list
    entity: todo.litellm_conversation_memories
    title: 🧠 What the assistant knows
  - type: entities
    entities:
      - entity: switch.litellm_conversation_transcript_capture
        name: Transcript capture
      - entity: sensor.litellm_conversation_last_dream
        name: Last dream
  - type: button
    name: 💤 Dream now
    icon: mdi:sleep
    tap_action:
      action: perform-action
      perform_action: litellm_conversation.dream
      data:
        include_activity: true
```

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

### Removal

1. Go to **Settings → Devices & Services → LiteLLM Conversation**, open the three-dot menu on the entry, and select **Delete**.
2. If installed via HACS: open HACS, find **LiteLLM Conversation**, three-dot menu → **Remove**. If installed manually: delete `config/custom_components/litellm_conversation/`.
3. **Restart Home Assistant.** All entities, subentries, and usage sensors are removed with the config entry; the integration stores no other data.

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

##### 📷 Vision: image attachments

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
│       ├── activity.py          # Logbook activity digest (dreaming input)
│       ├── ai_task.py           # AI Task platform (generate_data + attachments)
│       ├── config_flow.py       # Config + subentry UI flows
│       ├── const.py             # Constants, defaults
│       ├── conversation.py      # Conversation agent platform (+ transcript capture)
│       ├── diagnostics.py       # Redacted diagnostics export
│       ├── dreaming.py          # Background memory consolidation
│       ├── entity.py            # Base entity, request building, streaming, attachments
│       ├── extended_tools.py    # Extended Tools LLM API (9 tools)
│       ├── memory.py            # Long-term memory store
│       ├── schemas.py           # Subentry form schemas
│       ├── sensor.py            # Usage sensors + last-dream sensor
│       ├── services.py          # remember/forget/dream/clear_transcripts
│       ├── stt.py               # Speech-to-text platform
│       ├── switch.py            # Transcript capture toggle
│       ├── todo.py              # Memories as a native to-do list
│       ├── transcripts.py       # Rolling conversation transcript buffer
│       ├── tts.py               # Text-to-speech platform
│       ├── util.py              # Shared helpers
│       ├── manifest.json        # Integration metadata
│       ├── strings.json         # UI strings (English)
│       └── translations/        # i18n translations
├── blueprints/
│   └── automation/
│       └── nightly_dreaming.yaml  # Importable nightly-dream automation
├── tests/                       # Pytest suite (pytest-homeassistant-custom-component)
├── .devcontainer/               # VS Code dev container config
├── .github/workflows/ci.yml    # CI: ruff + pytest + hassfest + HACS validation
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
