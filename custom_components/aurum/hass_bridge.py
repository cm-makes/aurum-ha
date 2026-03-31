"""
AURUM – Home Assistant Bridge
==============================
Adapts HA Core APIs to the simple interface that modules expect.
Modules call self.hass.get_state() / self.hass.log() etc.
This bridge translates those to HA Core equivalents.
"""

import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class HassAccess:
    """Bridge between AURUM modules and HA Core API."""

    def __init__(self, hass: HomeAssistant):
        self._hass = hass

    def get_state(self, entity_id, attribute=None, default=None):
        """Read entity state or attribute."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return default

        if attribute == "all":
            return {
                "state": state.state,
                "attributes": dict(state.attributes),
            }

        if attribute:
            return state.attributes.get(attribute, default)

        return state.state

    def set_state(self, entity_id, state, attributes=None):
        """Set an entity state (for virtual sensors)."""
        self._hass.states.async_set(
            entity_id, state, attributes or {})

    def call_service(self, service, **kwargs):
        """Call a HA service (fire-and-forget, safe in async context)."""
        domain, service_name = service.split("/", 1)
        self._hass.services.call(
            domain, service_name, kwargs, blocking=False)

    def turn_on(self, entity_id, **kwargs):
        """Turn on a switch/input_boolean."""
        domain = entity_id.split(".")[0]
        self._hass.services.call(
            domain, "turn_on",
            {"entity_id": entity_id, **kwargs},
            blocking=False)

    def turn_off(self, entity_id, **kwargs):
        """Turn off a switch/input_boolean."""
        domain = entity_id.split(".")[0]
        self._hass.services.call(
            domain, "turn_off",
            {"entity_id": entity_id, **kwargs},
            blocking=False)

    def log(self, msg, level="INFO"):
        """Log a message."""
        log_fn = getattr(_LOGGER, level.lower(), _LOGGER.info)
        log_fn(msg)

    @property
    def config_path(self):
        """Return HA config directory path."""
        return self._hass.config.config_dir
