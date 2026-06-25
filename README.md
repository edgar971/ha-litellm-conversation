# LiteLLM Conversation

A Home Assistant custom component that integrates [LiteLLM](https://docs.litellm.ai/) as a conversation agent, enabling you to use any LLM provider supported by LiteLLM (OpenAI, Anthropic, Ollama, Azure, etc.) with Home Assistant's conversation and AI task features.

## Features

- Conversation agent backed by any LiteLLM-compatible endpoint
- Streaming responses
- Tool/function calling for HA device control (via LLM API)
- Configurable model, temperature, top-p, and max tokens per subentry
- Custom system prompt support

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** → three-dot menu → **Custom repositories**.
3. Add `https://github.com/edgarpino/ha-litellm-conversation` with category **Integration**.
4. Search for **LiteLLM Conversation** and install it.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/litellm_conversation` directory into your HA `config/custom_components/` folder.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **LiteLLM Conversation**.
3. Enter your LiteLLM proxy URL (e.g. `http://localhost:4000`) and API key.
4. Add a **conversation** subentry and choose your model.
5. Assign the agent in **Settings** → **Voice assistants**.

## LiteLLM Documentation

See the [LiteLLM docs](https://docs.litellm.ai/) for setting up a proxy and supported providers.
