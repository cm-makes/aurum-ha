"""
AURUM – Config Flow & Options Flow
====================================
Step 1: Energy sources (grid, PV, battery SOC)
Step 2: Battery settings (capacity, target SOC, min SOC)
Options: Add/edit/remove devices
"""

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_GRID_POWER_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_CAPACITY_WH,
    CONF_TARGET_SOC,
    CONF_MIN_SOC,
    CONF_UPDATE_INTERVAL,
    CONF_DEVICES,
    CONF_DEV_NAME,
    CONF_DEV_SWITCH_ENTITY,
    CONF_DEV_POWER_ENTITY,
    CONF_DEV_NOMINAL_POWER,
    CONF_DEV_PRIORITY,
    CONF_DEV_SOC_THRESHOLD,
    CONF_DEV_STARTUP_DETECTION,
    CONF_DEV_HYSTERESIS_ON,
    CONF_DEV_HYSTERESIS_OFF,
    CONF_DEV_DEBOUNCE_ON,
    CONF_DEV_DEBOUNCE_OFF,
    CONF_DEV_MIN_ON_TIME,
    CONF_DEV_MIN_OFF_TIME,
    CONF_DEV_DEADLINE,
    CONF_DEV_ESTIMATED_RUNTIME,
    CONF_DEV_INTERRUPTIBLE,
    CONF_DEV_MANUAL_OVERRIDE_ENTITY,
    CONF_DEV_MUSS_HEUTE_ENTITY,
    CONF_DEV_RESIDUAL_POWER,
    DEFAULT_BATTERY_CAPACITY_WH,
    DEFAULT_TARGET_SOC,
    DEFAULT_MIN_SOC,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_DEV_NOMINAL_POWER,
    DEFAULT_DEV_PRIORITY,
    DEFAULT_DEV_SOC_THRESHOLD,
    DEFAULT_DEV_HYSTERESIS_ON,
    DEFAULT_DEV_HYSTERESIS_OFF,
    DEFAULT_DEV_DEBOUNCE_ON,
    DEFAULT_DEV_DEBOUNCE_OFF,
    DEFAULT_DEV_MIN_ON_TIME,
    DEFAULT_DEV_MIN_OFF_TIME,
    DEFAULT_DEV_RESIDUAL_POWER,
)

_LOGGER = logging.getLogger(__name__)

# ── Selectors ────────────────────────────────────────────────────
_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor"))
_SWITCH = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "input_boolean"]))
_INPUT_BOOLEAN = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="input_boolean"))


def _schema_energy(defaults: dict | None = None) -> vol.Schema:
    """Schema for Step 1: Energy sources."""
    d = defaults or {}
    return vol.Schema({
        vol.Required(
            CONF_GRID_POWER_ENTITY,
            default=d.get(CONF_GRID_POWER_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_PV_POWER_ENTITY,
            default=d.get(CONF_PV_POWER_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_BATTERY_SOC_ENTITY,
            default=d.get(CONF_BATTERY_SOC_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
    })


def _schema_battery(defaults: dict | None = None) -> vol.Schema:
    """Schema for Step 2: Battery settings."""
    d = defaults or {}
    return vol.Schema({
        vol.Required(
            CONF_BATTERY_CAPACITY_WH,
            default=d.get(CONF_BATTERY_CAPACITY_WH, DEFAULT_BATTERY_CAPACITY_WH),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=500, max=100000, step=100,
            unit_of_measurement="Wh",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Required(
            CONF_TARGET_SOC,
            default=d.get(CONF_TARGET_SOC, DEFAULT_TARGET_SOC),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=10, max=100, step=5,
            unit_of_measurement="%",
            mode=selector.NumberSelectorMode.SLIDER)),
        vol.Required(
            CONF_MIN_SOC,
            default=d.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=50, step=5,
            unit_of_measurement="%",
            mode=selector.NumberSelectorMode.SLIDER)),
        vol.Required(
            CONF_UPDATE_INTERVAL,
            default=d.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=5, max=300, step=5,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
    })


def _schema_add_device(defaults: dict | None = None) -> vol.Schema:
    """Schema for adding/editing a device."""
    d = defaults or {}
    return vol.Schema({
        vol.Required(
            CONF_DEV_NAME,
            default=d.get(CONF_DEV_NAME, vol.UNDEFINED),
        ): selector.TextSelector(),
        vol.Required(
            CONF_DEV_SWITCH_ENTITY,
            default=d.get(CONF_DEV_SWITCH_ENTITY, vol.UNDEFINED),
        ): _SWITCH,
        vol.Optional(
            CONF_DEV_POWER_ENTITY,
            default=d.get(CONF_DEV_POWER_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Required(
            CONF_DEV_NOMINAL_POWER,
            default=d.get(CONF_DEV_NOMINAL_POWER, DEFAULT_DEV_NOMINAL_POWER),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=10, max=10000, step=10,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Required(
            CONF_DEV_PRIORITY,
            default=d.get(CONF_DEV_PRIORITY, DEFAULT_DEV_PRIORITY),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=100, step=1,
            mode=selector.NumberSelectorMode.SLIDER)),
        vol.Required(
            CONF_DEV_SOC_THRESHOLD,
            default=d.get(CONF_DEV_SOC_THRESHOLD, DEFAULT_DEV_SOC_THRESHOLD),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=100, step=5,
            unit_of_measurement="%",
            mode=selector.NumberSelectorMode.SLIDER)),
        vol.Optional(
            CONF_DEV_STARTUP_DETECTION,
            default=d.get(CONF_DEV_STARTUP_DETECTION, False),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_DEV_DEADLINE,
            default=d.get(CONF_DEV_DEADLINE, vol.UNDEFINED),
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_DEV_ESTIMATED_RUNTIME,
            default=d.get(CONF_DEV_ESTIMATED_RUNTIME, vol.UNDEFINED),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=10, max=480, step=10,
            unit_of_measurement="min",
            mode=selector.NumberSelectorMode.BOX)),
        # ── Behavior ──────────────────────────────────────────
        vol.Optional(
            CONF_DEV_INTERRUPTIBLE,
            default=d.get(CONF_DEV_INTERRUPTIBLE, True),
        ): selector.BooleanSelector(),
        vol.Optional(
            CONF_DEV_MANUAL_OVERRIDE_ENTITY,
            default=d.get(CONF_DEV_MANUAL_OVERRIDE_ENTITY, vol.UNDEFINED),
        ): _INPUT_BOOLEAN,
        vol.Optional(
            CONF_DEV_MUSS_HEUTE_ENTITY,
            default=d.get(CONF_DEV_MUSS_HEUTE_ENTITY, vol.UNDEFINED),
        ): _INPUT_BOOLEAN,
        vol.Optional(
            CONF_DEV_RESIDUAL_POWER,
            default=d.get(CONF_DEV_RESIDUAL_POWER, DEFAULT_DEV_RESIDUAL_POWER),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=1000, step=10,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        # ── Timing (advanced) ────────────────────────────────
        vol.Optional(
            CONF_DEV_HYSTERESIS_ON,
            default=d.get(CONF_DEV_HYSTERESIS_ON, DEFAULT_DEV_HYSTERESIS_ON),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=2000, step=10,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_HYSTERESIS_OFF,
            default=d.get(CONF_DEV_HYSTERESIS_OFF, DEFAULT_DEV_HYSTERESIS_OFF),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=2000, step=10,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_DEBOUNCE_ON,
            default=d.get(CONF_DEV_DEBOUNCE_ON, DEFAULT_DEV_DEBOUNCE_ON),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=1800, step=10,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_DEBOUNCE_OFF,
            default=d.get(CONF_DEV_DEBOUNCE_OFF, DEFAULT_DEV_DEBOUNCE_OFF),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=1800, step=10,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_MIN_ON_TIME,
            default=d.get(CONF_DEV_MIN_ON_TIME, DEFAULT_DEV_MIN_ON_TIME),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=3600, step=10,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_MIN_OFF_TIME,
            default=d.get(CONF_DEV_MIN_OFF_TIME, DEFAULT_DEV_MIN_OFF_TIME),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=3600, step=10,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
    })


# ═══════════════════════════════════════════════════════════════════
#  Config Flow (initial setup)
# ═══════════════════════════════════════════════════════════════════

class AurumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """AURUM config flow – 2-step wizard."""

    VERSION = 1

    def __init__(self):
        """Initialize flow."""
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1/2: Energy sources."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery()

        return self.async_show_form(
            step_id="user",
            data_schema=_schema_energy(),
        )

    async def async_step_battery(self, user_input=None):
        """Step 2/2: Battery settings."""
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_DEVICES] = []
            await self.async_set_unique_id("aurum_main")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="AURUM",
                data=self._data,
            )

        return self.async_show_form(
            step_id="battery",
            data_schema=_schema_battery(),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return options flow handler."""
        return AurumOptionsFlowHandler(config_entry)


# ═══════════════════════════════════════════════════════════════════
#  Options Flow (settings + device management)
# ═══════════════════════════════════════════════════════════════════

class AurumOptionsFlowHandler(config_entries.OptionsFlow):
    """AURUM options flow – settings + add/edit/remove devices."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry
        self._current = {**config_entry.data, **config_entry.options}
        self._options: dict = {}
        self._devices: list = list(self._current.get(CONF_DEVICES, []))

    async def async_step_init(self, user_input=None):
        """Entry point – choose what to do."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "settings":
                return await self.async_step_settings()
            elif action == "add_device":
                return await self.async_step_add_device()
            elif action == "edit_device":
                return await self.async_step_edit_device_select()
            elif action == "remove_device":
                return await self.async_step_remove_device()

        device_names = [d["name"] for d in self._devices]
        description = f"{len(self._devices)} devices configured"
        if device_names:
            description += f": {', '.join(device_names)}"

        options = [
            selector.SelectOptionDict(
                value="settings",
                label="menu_edit_energy"),
            selector.SelectOptionDict(
                value="add_device",
                label="menu_add_device"),
        ]
        if self._devices:
            options.append(selector.SelectOptionDict(
                value="edit_device",
                label="menu_edit_device"))
            options.append(selector.SelectOptionDict(
                value="remove_device",
                label="menu_remove_device"))

        return self.async_show_form(
            step_id="init",
            description_placeholders={"device_list": description},
            data_schema=vol.Schema({
                vol.Required("action", default="add_device"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        translation_key="action",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def async_step_settings(self, user_input=None):
        """Edit energy + battery settings."""
        if user_input is not None:
            self._options.update(user_input)
            self._options[CONF_DEVICES] = self._devices
            return self.async_create_entry(title="", data=self._options)

        combined = {**self._current, **self._options}
        all_schema = {}
        for key, val in _schema_energy(combined).schema.items():
            all_schema[key] = val
        for key, val in _schema_battery(combined).schema.items():
            all_schema[key] = val

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(all_schema),
        )

    async def async_step_add_device(self, user_input=None):
        """Add a new device."""
        if user_input is not None:
            self._devices.append(user_input)
            self._options[CONF_DEVICES] = self._devices
            return self.async_create_entry(title="", data={
                **self._current, **self._options,
            })

        return self.async_show_form(
            step_id="add_device",
            data_schema=_schema_add_device(),
        )

    async def async_step_edit_device_select(self, user_input=None):
        """Select a device to edit."""
        if not self._devices:
            return await self.async_step_init()

        if user_input is not None:
            name = user_input.get("device_to_edit")
            self._edit_device_name = name
            return await self.async_step_edit_device()

        device_names = [d["name"] for d in self._devices]
        return self.async_show_form(
            step_id="edit_device_select",
            data_schema=vol.Schema({
                vol.Required("device_to_edit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_names,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_edit_device(self, user_input=None):
        """Edit a device's settings."""
        name = self._edit_device_name
        dev = next((d for d in self._devices if d["name"] == name), None)
        if dev is None:
            return await self.async_step_init()

        if user_input is not None:
            # Replace the device in the list
            self._devices = [
                user_input if d["name"] == name else d
                for d in self._devices
            ]
            self._options[CONF_DEVICES] = self._devices
            return self.async_create_entry(title="", data={
                **self._current, **self._options,
            })

        return self.async_show_form(
            step_id="edit_device",
            data_schema=_schema_add_device(dev),
        )

    async def async_step_remove_device(self, user_input=None):
        """Remove an existing device."""
        if not self._devices:
            return await self.async_step_init()

        if user_input is not None:
            name = user_input.get("device_to_remove")
            self._devices = [d for d in self._devices if d["name"] != name]
            self._options[CONF_DEVICES] = self._devices
            return self.async_create_entry(title="", data={
                **self._current, **self._options,
            })

        device_names = [d["name"] for d in self._devices]
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("device_to_remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_names,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )
