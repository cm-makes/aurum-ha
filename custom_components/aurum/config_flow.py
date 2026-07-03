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

# Device slugs that would collide with AURUM's own hub entity object_ids
# (sensor.aurum_{slug} / _power / _energy_today / _active derivations).
_RESERVED_SLUGS = {
    "pv_power", "grid_power", "battery_soc", "battery_charge",
    "battery_discharge", "battery_mode", "excess_power", "budget",
    "house_consumption", "forecast_remaining", "energy_today", "cycle",
    "safety_factor", "electricity_price", "cheap_grid_active",
    # prefixes whose per-device suffixes collide with hub ids:
    "pv", "grid", "battery", "energy", "cheap_grid",
}

from .const import (
    DOMAIN,
    CONF_GRID_POWER_ENTITY,
    CONF_PV_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_CHARGE_POWER_ENTITY,
    CONF_BATTERY_DISCHARGE_POWER_ENTITY,
    CONF_PV_FORECAST_ENTITY,
    CONF_PV_FORECAST_TODAY_ENTITY,
    CONF_PV_ACTUAL_TODAY_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_BATTERY_CAPACITY_WH,
    CONF_TARGET_SOC,
    CONF_MIN_SOC,
    CONF_UPDATE_INTERVAL,
    CONF_NOTIFY_SERVICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_LEVEL_ENTITY,
    CONF_CHEAP_PERIOD_ENTITY,
    CONF_CHEAP_PERIOD_STARTS_IN_ENTITY,
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
    CONF_DEV_STOP_AFTER_RUNTIME,
    CONF_DEV_INTERRUPTIBLE,
    CONF_DEV_RESIDUAL_POWER,
    CONF_DEV_PRICE_MODE,
    CONF_DEV_MAX_PRICE,
    PRICE_MODE_SOLAR_ONLY,
    PRICE_MODE_CHEAP_GRID,
    CONF_DEV_SD_POWER_THRESHOLD,
    CONF_DEV_SD_DETECTION_TIME,
    CONF_DEV_SD_STANDBY_POWER,
    CONF_DEV_SD_FINISH_POWER,
    CONF_DEV_SD_FINISH_TIME,
    CONF_DEV_SD_MAX_RUNTIME,
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
    DEFAULT_DEV_SD_POWER_THRESHOLD,
    DEFAULT_DEV_SD_DETECTION_TIME,
    DEFAULT_DEV_SD_STANDBY_POWER,
    DEFAULT_DEV_SD_FINISH_POWER,
    DEFAULT_DEV_SD_FINISH_TIME,
    DEFAULT_DEV_SD_MAX_RUNTIME,
)

_LOGGER = logging.getLogger(__name__)

# ── Selectors ────────────────────────────────────────────────────
_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor"))
_WEATHER = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="weather"))
_SWITCH = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "input_boolean"]))
_BINARY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="binary_sensor"))


# ── Validation ───────────────────────────────────────────────────
_VALID_POWER_UNITS = {"W", "kW", "mW", "MW"}
_VALID_ENERGY_UNITS = {"Wh", "kWh", "MWh"}
_VALID_PERCENT_UNITS = {"%", ""}


def _is_numeric(value) -> bool | None:
    """Return True if numeric, False if clearly not, None if unverifiable."""
    if value is None or value in ("unknown", "unavailable", ""):
        return None
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _validate_energy_sources(hass, data: dict) -> dict[str, str]:
    """Catch the most common config mistakes before they cause silent runtime bugs.

    Returns a dict of field_name -> error_key. Empty dict = OK.
    Only flags clear errors (wrong unit, fraction-vs-percent SOC); tolerates
    transient unknown/unavailable states.
    """
    errors: dict[str, str] = {}

    def _check_power(key: str) -> None:
        ent = data.get(key)
        if not ent:
            return
        st = hass.states.get(ent)
        if st is None:
            errors[key] = "entity_not_found"
            return
        unit = (st.attributes.get("unit_of_measurement") or "").strip()
        if unit and unit not in _VALID_POWER_UNITS:
            errors[key] = "invalid_power_unit"
        elif _is_numeric(st.state) is False:
            errors[key] = "not_numeric"

    def _check_energy(key: str) -> None:
        ent = data.get(key)
        if not ent:
            return
        st = hass.states.get(ent)
        if st is None:
            errors[key] = "entity_not_found"
            return
        unit = (st.attributes.get("unit_of_measurement") or "").strip()
        if unit and unit not in _VALID_ENERGY_UNITS:
            errors[key] = "invalid_energy_unit"

    _check_power(CONF_GRID_POWER_ENTITY)
    _check_power(CONF_PV_POWER_ENTITY)
    _check_power(CONF_BATTERY_CHARGE_POWER_ENTITY)
    _check_power(CONF_BATTERY_DISCHARGE_POWER_ENTITY)
    _check_energy(CONF_PV_FORECAST_ENTITY)
    _check_energy(CONF_PV_ACTUAL_TODAY_ENTITY)

    soc = data.get(CONF_BATTERY_SOC_ENTITY)
    if soc:
        st = hass.states.get(soc)
        if st is None:
            errors[CONF_BATTERY_SOC_ENTITY] = "entity_not_found"
        else:
            unit = (st.attributes.get("unit_of_measurement") or "").strip()
            if unit and unit not in _VALID_PERCENT_UNITS:
                errors[CONF_BATTERY_SOC_ENTITY] = "invalid_soc_unit"
            elif _is_numeric(st.state):
                val = float(st.state)
                if 0 < val <= 1:
                    errors[CONF_BATTERY_SOC_ENTITY] = "soc_is_fraction"

    return errors


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
        vol.Optional(
            CONF_BATTERY_CHARGE_POWER_ENTITY,
            default=d.get(CONF_BATTERY_CHARGE_POWER_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_BATTERY_DISCHARGE_POWER_ENTITY,
            default=d.get(CONF_BATTERY_DISCHARGE_POWER_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_PV_FORECAST_ENTITY,
            default=d.get(CONF_PV_FORECAST_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_PV_FORECAST_TODAY_ENTITY,
            default=d.get(CONF_PV_FORECAST_TODAY_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_PV_ACTUAL_TODAY_ENTITY,
            default=d.get(CONF_PV_ACTUAL_TODAY_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_WEATHER_ENTITY,
            default=d.get(CONF_WEATHER_ENTITY, vol.UNDEFINED),
        ): _WEATHER,
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
        vol.Optional(
            CONF_NOTIFY_SERVICE,
            description={"suggested_value": d.get(CONF_NOTIFY_SERVICE, "")},
        ): selector.TextSelector(selector.TextSelectorConfig(
            type=selector.TextSelectorType.TEXT)),
        vol.Optional(
            CONF_PRICE_ENTITY,
            default=d.get(CONF_PRICE_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_PRICE_LEVEL_ENTITY,
            default=d.get(CONF_PRICE_LEVEL_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
        vol.Optional(
            CONF_CHEAP_PERIOD_ENTITY,
            default=d.get(CONF_CHEAP_PERIOD_ENTITY, vol.UNDEFINED),
        ): _BINARY_SENSOR,
        vol.Optional(
            CONF_CHEAP_PERIOD_STARTS_IN_ENTITY,
            default=d.get(CONF_CHEAP_PERIOD_STARTS_IN_ENTITY, vol.UNDEFINED),
        ): _SENSOR,
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
        # ── Startup Detection parameters (visible when SD is enabled) ──
        vol.Optional(
            CONF_DEV_SD_POWER_THRESHOLD,
            default=d.get(CONF_DEV_SD_POWER_THRESHOLD,
                          DEFAULT_DEV_SD_POWER_THRESHOLD),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=500, step=1,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_SD_STANDBY_POWER,
            default=d.get(CONF_DEV_SD_STANDBY_POWER,
                          DEFAULT_DEV_SD_STANDBY_POWER),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=100, step=1,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_SD_FINISH_POWER,
            default=d.get(CONF_DEV_SD_FINISH_POWER,
                          DEFAULT_DEV_SD_FINISH_POWER),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=100, step=1,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_SD_FINISH_TIME,
            default=d.get(CONF_DEV_SD_FINISH_TIME,
                          DEFAULT_DEV_SD_FINISH_TIME),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=30, max=1800, step=30,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_SD_DETECTION_TIME,
            default=d.get(CONF_DEV_SD_DETECTION_TIME,
                          DEFAULT_DEV_SD_DETECTION_TIME),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=1, max=60, step=1,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_SD_MAX_RUNTIME,
            default=d.get(CONF_DEV_SD_MAX_RUNTIME,
                          DEFAULT_DEV_SD_MAX_RUNTIME),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=600, max=18000, step=600,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_DEADLINE,
            default=d.get(CONF_DEV_DEADLINE, vol.UNDEFINED),
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_DEV_ESTIMATED_RUNTIME,
            default=d.get(CONF_DEV_ESTIMATED_RUNTIME, vol.UNDEFINED),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=10, max=1440, step=10,
            unit_of_measurement="min",
            mode=selector.NumberSelectorMode.BOX)),
        vol.Optional(
            CONF_DEV_STOP_AFTER_RUNTIME,
            default=d.get(CONF_DEV_STOP_AFTER_RUNTIME, False),
        ): selector.BooleanSelector(),
        # ── Behavior ──────────────────────────────────────────
        vol.Optional(
            CONF_DEV_INTERRUPTIBLE,
            default=d.get(CONF_DEV_INTERRUPTIBLE, True),
        ): selector.BooleanSelector(),
        # Note: manual_override and muss_heute are now auto-created as
        # switch entities (switch.aurum_{slug}_override / _muss_heute).
        # Legacy manual_override_entity / muss_heute_entity configs
        # remain supported as fallback but no longer shown in the UI.
        # ── Price-aware scheduling ───────────────────────────
        vol.Optional(
            CONF_DEV_PRICE_MODE,
            default=d.get(CONF_DEV_PRICE_MODE, PRICE_MODE_SOLAR_ONLY),
        ): selector.SelectSelector(selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=PRICE_MODE_SOLAR_ONLY,
                    label="price_mode_solar_only"),
                selector.SelectOptionDict(
                    value=PRICE_MODE_CHEAP_GRID,
                    label="price_mode_cheap_grid"),
            ],
            translation_key="price_mode",
            mode=selector.SelectSelectorMode.DROPDOWN,
        )),
        vol.Optional(
            CONF_DEV_MAX_PRICE,
            default=d.get(CONF_DEV_MAX_PRICE, 0),
        ): selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=100, step=1,
            unit_of_measurement="ct/kWh",
            mode=selector.NumberSelectorMode.BOX)),
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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_energy_sources(self.hass, user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_battery()

        return self.async_show_form(
            step_id="user",
            data_schema=_schema_energy(user_input or {}),
            errors=errors,
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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_energy_sources(self.hass, user_input)
            if not errors:
                self._options.update(user_input)
                self._options[CONF_DEVICES] = self._devices
                return self.async_create_entry(title="", data=self._options)

        combined = {**self._current, **self._options, **(user_input or {})}
        all_schema = {}
        for key, val in _schema_energy(combined).schema.items():
            all_schema[key] = val
        for key, val in _schema_battery(combined).schema.items():
            all_schema[key] = val

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(all_schema),
            errors=errors,
        )

    async def async_step_add_device(self, user_input=None):
        """Add a new device."""
        errors: dict[str, str] = {}
        if user_input is not None:
            from .modules.helpers import slugify as _slugify
            new_slug = _slugify(user_input.get(CONF_DEV_NAME, ""))
            existing = {
                _slugify(d.get(CONF_DEV_NAME, "")) for d in self._devices}
            if not new_slug:
                errors["base"] = "invalid_device_name"
            elif new_slug in _RESERVED_SLUGS:
                errors["base"] = "reserved_device_name"
            elif new_slug in existing:
                # Entity unique_ids derive from the slug; a duplicate would
                # collide/overwrite the existing device's entities.
                errors["base"] = "duplicate_device"
            else:
                self._devices.append(user_input)
                self._options[CONF_DEVICES] = self._devices
                return self.async_create_entry(title="", data={
                    **self._current, **self._options,
                })

        return self.async_show_form(
            step_id="add_device",
            data_schema=_schema_add_device(user_input),
            errors=errors,
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

        errors: dict[str, str] = {}
        if user_input is not None:
            from .modules.helpers import slugify as _slugify
            new_slug = _slugify(user_input.get(CONF_DEV_NAME, ""))
            # Slugs of all OTHER devices (exclude the one being edited).
            others = {
                _slugify(d.get(CONF_DEV_NAME, ""))
                for d in self._devices if d["name"] != name}
            if not new_slug:
                errors["base"] = "invalid_device_name"
            elif new_slug in _RESERVED_SLUGS:
                errors["base"] = "reserved_device_name"
            elif new_slug in others:
                # Entity unique_ids derive from the slug; renaming onto an
                # existing slug would collide/overwrite the other device.
                errors["base"] = "duplicate_device"
            else:
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
            data_schema=_schema_add_device(user_input or dev),
            errors=errors,
        )

    async def async_step_remove_device(self, user_input=None):
        """Remove an existing device."""
        if not self._devices:
            return await self.async_step_init()

        if user_input is not None:
            name = user_input.get("device_to_remove")
            # Capture device dict before removing it (needed for slug)
            removed_dev = next((d for d in self._devices if d["name"] == name), None)
            self._devices = [d for d in self._devices if d["name"] != name]
            self._options[CONF_DEVICES] = self._devices

            # Clean up all HA entity registry entries for the removed device
            if removed_dev:
                from homeassistant.helpers import entity_registry as er
                from .modules.helpers import slugify as _slugify
                slug = removed_dev.get("slug") or _slugify(name)
                # Slugs of the surviving devices (self._devices already has the
                # removed device filtered out). Used to disambiguate prefix
                # collisions: a slug that is a prefix of another device's slug
                # (e.g. "washer" vs "washer_2") must NOT match the other's
                # entities. We assign each entity to the device with the
                # LONGEST matching slug prefix and only remove ours.
                survivor_slugs = {
                    _slugify(d.get(CONF_DEV_NAME, "")) for d in self._devices}
                all_slugs = survivor_slugs | {slug}
                ent_reg = er.async_get(self.hass)
                entries = er.async_entries_for_config_entry(
                    ent_reg, self.config_entry.entry_id
                )
                for entry in entries:
                    object_id = entry.entity_id.split(".", 1)[-1]
                    # Candidate owners: every slug that matches this entity's
                    # object_id either exactly (the per-device status sensor
                    # is object_id "aurum_{slug}" with NO suffix) or as a
                    # bounded prefix (slug followed by "_suffix"). The
                    # longest-match arbitration below then prevents a
                    # prefix-slug (e.g. "washer") from claiming another
                    # device's entities (e.g. "washer_2").
                    candidates = [
                        s for s in all_slugs
                        if s and (object_id == f"aurum_{s}"
                                  or object_id.startswith(f"aurum_{s}_"))
                    ]
                    if not candidates:
                        continue
                    owner = max(candidates, key=len)
                    if owner == slug:
                        _LOGGER.debug(
                            "AURUM: removing entity %s (device '%s' deleted)",
                            entry.entity_id, name,
                        )
                        ent_reg.async_remove(entry.entity_id)

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
