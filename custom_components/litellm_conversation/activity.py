"""Household-activity digest for the dreaming layer.

Renders recent logbook events (the same data behind HA's activity feed)
into a compact text digest. Filtered to high-signal domains — automations,
presence, security — not every light toggle; raw logbook is firehose noise.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant

from .const import LOGGER

# Domains whose events teach household rhythm; everything else is noise.
ACTIVITY_DOMAINS = {
    "automation",
    "script",
    "person",
    "device_tracker",
    "lock",
    "alarm_control_panel",
    "cover",
    "climate",
    "binary_sensor",
}
MAX_ACTIVITY_EVENTS = 300


async def async_build_activity_digest(
    hass: HomeAssistant, start: datetime, end: datetime
) -> str | None:
    """Return a text digest of high-signal logbook activity, or None."""
    try:
        from homeassistant.components.logbook.processor import EventProcessor
    except ImportError:
        LOGGER.warning("Logbook integration not available; skipping activity digest")
        return None

    def _get_events() -> list[dict]:
        processor = EventProcessor(hass, ("state_changed",), timestamp=True)
        return list(processor.get_events(start, end))

    try:
        from homeassistant.components.recorder import get_instance

        events = await get_instance(hass).async_add_executor_job(_get_events)
    except Exception as err:
        LOGGER.warning("Activity digest failed: %s", err)
        return None

    lines: list[str] = []
    for event in events:
        entity_id = event.get("entity_id") or ""
        domain = entity_id.split(".")[0] if "." in entity_id else event.get("domain", "")
        if domain not in ACTIVITY_DOMAINS:
            continue
        name = event.get("name") or entity_id
        state = event.get("state") or event.get("message") or ""
        when = event.get("when", "")
        lines.append(f"[{when}] {name}: {state}")
        if len(lines) >= MAX_ACTIVITY_EVENTS:
            break

    if not lines:
        return None
    return "\n".join(lines)
