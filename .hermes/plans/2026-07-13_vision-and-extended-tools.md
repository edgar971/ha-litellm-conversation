# Vision (AI Task Attachments) + New Extended Tools — Implementation Plan

> **For Hermes:** Implement task-by-task, one atomic commit per task. Run tests + ruff after every task.

**Goal:** (A) AI Task entities accept image attachments (camera snapshots, media files) and pass them to vision-capable models via LiteLLM; (B) three new extended tools — `analyze_camera`, `get_calendar_events`, `add_todo_item` — so voice/Assist can "check the driveway", read calendars, and manage shopping lists.

**Architecture:** Follow core's `openai_conversation` attachment pattern adapted to Chat Completions: resolved `conversation.Attachment` objects are base64-encoded (in executor — file reads block) into `image_url` content parts appended to the last user message. `analyze_camera` is the bridge that gives *conversation* agents vision: the tool snapshots a camera via `camera.async_get_image`, makes a nested vision call through the integration's own LiteLLM client, and returns the text answer as the tool result (tool results are JSON — you can't hand the primary model raw pixels mid-conversation, so the nested-call design is the correct shape).

**Tech Stack:** HA `ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS`, `conversation.Attachment`, Chat Completions `image_url` data-URL parts, `camera.async_get_image`, `calendar.get_events` / `todo.add_item` services.

**Repo:** `~/dev/ha-litellm-conversation` (venv: `.venv`, Python 3.13). Verify env first:
`source .venv/bin/activate && python -m pytest tests/ -q` → expect 60 passed.

---

## Verified facts (don't re-derive)

- `conversation.Attachment`: dataclass with `media_content_id: str`, `mime_type: str`, `path: Path` (core `conversation/chat_log.py` ~L239).
- `conversation.UserContent` has `.attachments: list[Attachment] | None`.
- ai_task's `_resolve_attachments` handles `media-source://camera/...` IDs itself (snapshots to a temp file) — **we get a local file path for camera attachments for free**; no camera code needed on the AI Task path.
- Core's openai integration: images only + PDF; encodes with `base64.b64encode(path.read_bytes())` inside `hass.async_add_executor_job`; appends parts to the **last user message** when `last_content.role == "user" and last_content.attachments`.
- Chat Completions image part shape (LiteLLM translates for Bedrock Claude):
  `{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}`
- Bedrock Claude via LiteLLM: vision works on Chat Completions with data URLs. PDFs are NOT reliably supported on the Chat Completions path → **images only, raise `HomeAssistantError` otherwise** (YAGNI).
- `camera.async_get_image(hass, entity_id)` → `Image(content_type, content)` (bytes). Import from `homeassistant.components.camera`; add `camera` to `after_dependencies` (hassfest DEPENDENCIES check — lazy import still must be declared).
- `calendar.get_events` and `todo.get_items` are response services (`return_response=True`); `todo.add_item` is fire-and-forget.
- Exposure check for tools: `homeassistant.components.homeassistant.exposed_entities.async_should_expose(hass, "conversation", entity_id)`.

## Design decisions (confirm with Edgar before Task 6)

1. **`analyze_camera` vision model**: nested call uses the **same client** (entry.runtime_data) and a new optional const `CONF_VISION_MODEL` on the *extended tools*… but extended tools API is hass-global, not per-entry. Resolution: register-time closure — `async_register_extended_api(hass, entry)` already runs per entry; store `entry` on `ExtendedToolsAPI` and use `entry.runtime_data` + the first conversation subentry's `CONF_CHAT_MODEL` as the vision model. Simple, zero new config. (Add a dedicated vision-model config field only if a real need appears — same principle as the blocklist.)
2. **Camera guardrail**: `analyze_camera` only accepts camera entities **exposed to Assist** (`async_should_expose`). Prevents prompt-injected snooping of unexposed cameras. Hardcoded, not configurable.
3. **Attachment scope**: images only (`mime_type.startswith("image/")`). PDF → clear error message.
4. **Calendar/todo tools**: thin wrappers over response services rather than telling users "use call_service" — dedicated tools with tight schemas are dramatically more reliable for voice. Both check `async_should_expose` on the target entity.
5. **`get_weather_forecast`: skipped** — `call_service` already reaches `weather.get_forecasts` with `return_response`; no ergonomic win worth the surface area.

---

## Feature A: AI Task attachments (vision)

### Task 1: Encoding helper + tests

**Files:** Modify `custom_components/litellm_conversation/entity.py`; Create `tests/test_attachments.py`

Add to `entity.py` (near `_convert_content_to_messages`):

```python
async def async_prepare_attachment_parts(
    hass: HomeAssistant,
    attachments: list[conversation.Attachment],
) -> list[dict[str, Any]]:
    """Encode image attachments as Chat Completions image_url content parts."""

    def _encode(path: Path, mime_type: str) -> str:
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    parts: list[dict[str, Any]] = []
    for attachment in attachments:
        if not attachment.mime_type.startswith("image/"):
            raise HomeAssistantError(
                f"Only image attachments are supported; "
                f"{attachment.path.name} is {attachment.mime_type}"
            )
        b64 = await hass.async_add_executor_job(
            _encode, attachment.path, attachment.mime_type
        )
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{attachment.mime_type};base64,{b64}"},
            }
        )
    return parts
```

New imports: `base64`, `from pathlib import Path`, `from homeassistant.core import HomeAssistant` (check what's already imported).

**Tests** (`tests/test_attachments.py`): write FIRST, run to see them fail.
- happy path: tmp_path PNG bytes → one part, data URL prefix `data:image/png;base64,`, payload round-trips via `base64.b64decode`.
- two attachments → two parts, order preserved.
- `application/pdf` → `pytest.raises(HomeAssistantError)`.
Use a `SimpleNamespace(mime_type=..., path=..., media_content_id=...)` — no HA fixtures needed if you fake `hass.async_add_executor_job` with a 2-line async stub.

Run: `python -m pytest tests/test_attachments.py -v` → PASS. Commit: `feat: attachment-to-content-part encoding helper`

### Task 2: Wire attachments into the message builder

**Files:** Modify `entity.py` (`_convert_content_to_messages`, `_async_handle_chat_log`); Modify `tests/test_attachments.py`

`_convert_content_to_messages` is pure/sync — keep it that way. Add an optional param:

```python
def _convert_content_to_messages(
    chat_content: list[conversation.Content],
    last_user_attachment_parts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
```

In the `elif content.content:` branch, when this is the LAST content item, it's a user message, and parts were provided, emit multi-part content:

```python
messages.append({
    "role": content.role,
    "content": [{"type": "text", "text": content.content}, *last_user_attachment_parts],
})
```

(Match core: attachments ride on the last user message only.)

In `_async_handle_chat_log`, before the first `_convert_content_to_messages` call:

```python
attachment_parts: list[dict[str, Any]] | None = None
last_content = chat_log.content[-1] if chat_log.content else None
if (
    isinstance(last_content, conversation.UserContent)
    and last_content.attachments
):
    attachment_parts = await async_prepare_attachment_parts(
        self.hass, last_content.attachments
    )
create_params["messages"] = _convert_content_to_messages(
    chat_log.content, attachment_parts
)
```

The loop's follow-up rebuild (`create_params["messages"] = _convert_content_to_messages(chat_log.content)` at the bottom of the tool loop) must ALSO pass `attachment_parts` — otherwise the image vanishes on the second tool iteration and the model answers from memory. 

**Tests:** message-shape tests for `_convert_content_to_messages` with fake `UserContent` carrying attachments (existing tests show the fake-content pattern — check `tests/test_request_params.py` imports). Verify: last user message content is a list, text part first, non-last user messages unaffected.

Run full suite: `python -m pytest tests/ -q` → all pass. Commit: `feat: pass image attachments to the model as image_url parts`

### Task 3: Enable the feature flag + AI Task instructions

**Files:** Modify `custom_components/litellm_conversation/ai_task.py`

```python
_attr_supported_features = (
    ai_task.AITaskEntityFeature.GENERATE_DATA
    | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
)
```

Check core's `ai_task` const for the exact flag name first:
`curl -s https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/ai_task/const.py | grep -A5 EntityFeature`

Run suite + `python -m ruff check custom_components --config ruff.toml`. Commit: `feat(ai_task): advertise attachment support`

### Task 4: Live verification against llm.pinocasa.com

No commit — verification gate. Standalone script (NOT under `tests/`): POST a small image as a data-URL part to `/v1/chat/completions` with the Bedrock Sonnet model via the proxy (key: `~/.openclaw/openclaw.json` → `models.providers.litellm.apiKey`). Confirm the model describes the image. If Bedrock rejects the `image_url` shape through LiteLLM, STOP and investigate before proceeding (this is the one genuinely unverified assumption).

---

## Feature B: New extended tools

### Task 5: Refactor ExtendedToolsAPI registration to carry the config entry

**Files:** Modify `custom_components/litellm_conversation/extended_tools.py`, `custom_components/litellm_conversation/__init__.py`; Modify `tests/test_extended_tools.py`

- `ExtendedToolsAPI.__init__(self, hass, entry)` — store `self._entry = entry`.
- `async_register_extended_api(hass, entry)` — pass it through (update the `__init__.py` call site; keep the already-registered guard).
- Unloading: if the owning entry unloads, tools needing the client must fail gracefully (`{"error": "LiteLLM entry not loaded"}`) — check `entry.state is ConfigEntryState.LOADED` before using `runtime_data`.

Run existing extended-tools tests, fix constructor call sites. Commit: `refactor(extended_tools): API carries owning config entry`

### Task 6: `analyze_camera` tool

**Files:** Modify `extended_tools.py`; Modify `tests/test_extended_tools.py`

```python
class AnalyzeCameraTool(llm.Tool):
    name = "analyze_camera"
    description = (
        "Take a snapshot from a camera and answer a question about what it "
        "shows (e.g. 'Is there a package by the door?'). entity_id must be a "
        "camera entity; question is what you want to know about the image."
    )
    parameters = vol.Schema(
        {vol.Required("entity_id"): str, vol.Required("question"): str}
    )
```

`async_call` flow:
1. Validate `entity_id.startswith("camera.")` and state exists → else `{"error": ...}`.
2. Exposure guard: `async_should_expose(hass, conversation.DOMAIN, entity_id)` → else `{"error": "Camera not exposed to Assist"}`.
3. `image = await camera.async_get_image(hass, entity_id)` (wrap `HomeAssistantError` → `{"error": str(err)}`).
4. Base64 in executor, build one-shot vision request: system prompt "Answer concisely based only on the image.", user message = [text question, image part]. **Non-streaming** (`stream=False`, no stream_options), `max_tokens=500`, model = first conversation subentry's `CONF_CHAT_MODEL` (fall back to `DEFAULT_CHAT_MODEL`), `extra_body={"drop_params": True}`.
5. Return `{"camera": entity_id, "answer": response.choices[0].message.content}`.

Imports: lazy `from homeassistant.components import camera` inside the function + **add `"camera"` to `after_dependencies` in manifest.json** (keep keys alphabetically sorted — hassfest).

**Tests:** mock `camera.async_get_image` + the client; assert exposure rejection, non-camera rejection, happy-path answer passthrough, entry-not-loaded error. Follow the existing `test_extended_tools.py` mock patterns.

Commit: `feat(extended_tools): analyze_camera vision tool`

### Task 7: `get_calendar_events` tool

**Files:** Modify `extended_tools.py`; tests.

Schema: `entity_id` (required), `days_ahead` (optional int 1–30, default 7). Guards: `calendar.` prefix, exists, exposed. Call:

```python
result = await hass.services.async_call(
    "calendar", "get_events",
    {
        "entity_id": entity_id,
        "start_date_time": dt_util.now().isoformat(),
        "end_date_time": (dt_util.now() + timedelta(days=days)).isoformat(),
    },
    blocking=True, return_response=True,
)
```

Return the events list for the entity (cap at 50 events). Commit: `feat(extended_tools): get_calendar_events tool`

### Task 8: `add_todo_item` tool

**Files:** Modify `extended_tools.py`; tests.

Schema: `entity_id` (required, `todo.` prefix), `item` (required str), `description` (optional), `due_date` (optional, `YYYY-MM-DD`). Guards: prefix/exists/exposed. `todo.add_item` with `blocking=True`; return `{"success": True, "list": entity_id, "item": item}`. This makes "add milk to the shopping list" work by voice. Commit: `feat(extended_tools): add_todo_item tool`

### Task 9: Wire new tools into the API instance + prompt

**Files:** Modify `extended_tools.py` (`async_get_api_instance` tool list + `api_prompt` sentence mentioning the new tools).

Keep the prompt addition SHORT (one sentence listing tool names + "prefer standard intent tools for device control"). Full suite + ruff. Commit: `feat(extended_tools): register analyze_camera, calendar, todo tools`

---

## Wrap-up

### Task 10: Docs, quality scale, release

- README: new "Vision" section (AI Task attachments example YAML using `media-source://camera/camera.driveway` + the analyze_camera voice flow), extended-tools table rows, guardrails notes (exposure checks).
- While in README: knock out `docs-removal-instructions` (the last quality-scale `todo`).
- Bump `manifest.json` version → **1.4.0**; update NEXT_STEPS.md (attachments done).
- `python -m pytest tests/ -q` && ruff check + format → green.
- Commit `docs + chore(release): v1.4.0`, push, verify CI (`gh run list`), then `git tag v1.4.0 && git push origin v1.4.0` (HACS installs from tags).

### Task 11: Deploy + live smoke test (with Edgar)

Live HA lags the repo — HACS redownload + restart required (get Edgar's go-ahead; ~60–90 s downtime). Then:
1. `ai_task.generate_data` from Developer Tools with a camera attachment → structured answer.
2. Voice: "Is there anything in the driveway?" → agent calls `analyze_camera` → spoken answer.
3. "Add milk to the shopping list" → item appears in the todo list.

## Risks / open questions

| Risk | Mitigation |
| --- | --- |
| Bedrock via LiteLLM rejects `image_url` data URLs | Task 4 gate before building on it |
| Snapshot too large (Claude ~5 MB/image limit) | If Task 4 shows problems: downscale via executor + PIL — **don't add the dep preemptively** |
| `analyze_camera` doubles token spend (nested call) | Usage sensors don't capture the nested call — acceptable v1; note in README |
| Camera warm-up latency (Reolink RTSP ~1–3 s) | Fine for voice; note timeout behavior in tool description |
| Exposure check API location drift | Verify import path against current core before Task 6 |

**Open for Edgar:** (1) OK with same-model nested vision call (no separate vision-model config)? (2) Tool set scope — analyze_camera + calendar + todo, weather skipped? (3) v1.4.0 as the release number?
