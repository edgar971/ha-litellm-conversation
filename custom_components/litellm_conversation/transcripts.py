"""Rolling transcript buffer feeding the dreaming layer.

Passively captures conversation exchanges (user text + assistant reply —
never tool-call internals) into a Store-backed ring buffer so background
memory consolidation ("dreaming") has material to analyze. HA itself keeps
no conversation history (ChatLog is in-memory, GC'd after ~5 minutes), so
this buffer is the only conversation persistence — which is why capture is
user-toggleable via switch.*_transcript_capture.

Retention: ring-trimmed to MAX_EXCHANGES and MAX_AGE_DAYS, local only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import ulid as ulid_util

from .const import DOMAIN, LOGGER

TRANSCRIPT_STORAGE_KEY = f"{DOMAIN}.transcripts"
TRANSCRIPT_STORAGE_VERSION = 1

MAX_EXCHANGES = 200
MAX_AGE_DAYS = 7
MAX_TEXT_LENGTH = 2000  # per side, keeps dream prompts bounded


@dataclass
class Exchange:
    """One user→assistant exchange."""

    user_text: str
    assistant_text: str
    conversation_id: str
    id: str = field(default_factory=ulid_util.ulid_now)
    when: str = field(default_factory=lambda: dt_util.now().isoformat())

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-serializable dict."""
        return {
            "id": self.id,
            "when": self.when,
            "conversation_id": self.conversation_id,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
        }


class TranscriptBuffer:
    """Ring buffer of conversation exchanges + the dreaming watermark."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the buffer."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, TRANSCRIPT_STORAGE_VERSION, TRANSCRIPT_STORAGE_KEY
        )
        self._exchanges: list[Exchange] = []
        self.capture_enabled: bool = True
        self.last_dream_at: str | None = None
        self._loaded = False

    async def async_load(self) -> None:
        """Load from disk (idempotent)."""
        if self._loaded:
            return
        data = await self._store.async_load()
        if data:
            self._exchanges = [
                Exchange(
                    id=e["id"],
                    when=e["when"],
                    conversation_id=e["conversation_id"],
                    user_text=e["user_text"],
                    assistant_text=e["assistant_text"],
                )
                for e in data.get("exchanges", [])
            ]
            self.capture_enabled = data.get("capture_enabled", True)
            self.last_dream_at = data.get("last_dream_at")
        self._trim()
        self._loaded = True
        LOGGER.debug("Loaded %d transcript exchanges", len(self._exchanges))

    @callback
    def _save(self) -> None:
        """Persist (debounced)."""
        self._store.async_delay_save(
            lambda: {
                "exchanges": [e.as_dict() for e in self._exchanges],
                "capture_enabled": self.capture_enabled,
                "last_dream_at": self.last_dream_at,
            },
            2.0,
        )

    def _trim(self) -> None:
        """Enforce count and age caps."""
        cutoff = (dt_util.now() - timedelta(days=MAX_AGE_DAYS)).isoformat()
        self._exchanges = [e for e in self._exchanges if e.when >= cutoff]
        if len(self._exchanges) > MAX_EXCHANGES:
            self._exchanges = self._exchanges[-MAX_EXCHANGES:]

    def add_exchange(self, user_text: str, assistant_text: str, conversation_id: str) -> None:
        """Record one exchange (no-op while capture is disabled)."""
        if not self.capture_enabled:
            return
        if not user_text.strip() or not assistant_text.strip():
            return
        self._exchanges.append(
            Exchange(
                user_text=user_text.strip()[:MAX_TEXT_LENGTH],
                assistant_text=assistant_text.strip()[:MAX_TEXT_LENGTH],
                conversation_id=conversation_id,
            )
        )
        self._trim()
        self._save()

    def set_capture_enabled(self, enabled: bool) -> None:
        """Toggle capture (existing buffer is kept — pausing is not purging)."""
        self.capture_enabled = enabled
        self._save()

    def clear(self) -> int:
        """Wipe the buffer. Returns the number of exchanges removed."""
        removed = len(self._exchanges)
        self._exchanges = []
        self._save()
        return removed

    def exchanges_since_last_dream(self) -> list[Exchange]:
        """Return exchanges newer than the dreaming watermark."""
        if self.last_dream_at is None:
            return list(self._exchanges)
        return [e for e in self._exchanges if e.when > self.last_dream_at]

    def mark_dreamed(self) -> None:
        """Advance the watermark to now."""
        self.last_dream_at = dt_util.now().isoformat()
        self._save()

    @property
    def exchange_count(self) -> int:
        """Total exchanges currently buffered."""
        return len(self._exchanges)


@callback
def async_get_transcript_buffer(hass: HomeAssistant) -> TranscriptBuffer:
    """Get or create the singleton transcript buffer (load separately)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "transcript_buffer" not in domain_data:
        domain_data["transcript_buffer"] = TranscriptBuffer(hass)
    return domain_data["transcript_buffer"]
