"""
AURUM – Configured entities that no longer exist
=================================================
Finds entities in AURUM's configuration that Home Assistant does not
have: renamed (for example with "Recreate entity IDs"), disabled, or
removed together with their device or integration. Such an entity fails
silently: startup detection never sees a program start without its power
sensor, a run condition without its sensor does not apply, a price or
forecast sensor gives no data.

Existence only. An entity that exists but is unavailable is handled
where it is read (input health in energy.py, the device logic). That
includes a registered entity whose integration failed to load: HA gives
it an "unavailable" placeholder state.

Two-pass: an entity is reported only when it is still missing
CONFIRM_S after a check first found it missing, with no check in between
that found it. Cloud integrations create their entities minutes after
start, and an integration reload removes its entities for a moment;
neither raises a false alarm. The coordinator starts checking once Home
Assistant is running and AURUM's startup has ended, then every
CHECK_INTERVAL_S: a reported entity that exists again is dropped at the
next check.
"""

# Hub fields in the order of the settings form, then the device fields.
HUB_FIELDS = (
    "grid_power_entity",
    "pv_power_entity",
    "battery_soc_entity",
    "battery_charge_power_entity",
    "battery_discharge_power_entity",
    "pv_forecast_entity",
    "pv_forecast_today_entity",
    "pv_actual_today_entity",
    "weather_entity",
    "price_entity",
    "price_level_entity",
    "cheap_period_entity",
    "cheap_period_starts_in_entity",
)
DEVICE_FIELDS = ("switch_entity", "power_entity", "condition_entity")

# The field labels of the settings forms (without "(optional)"), so the
# repair issue names the field the user has to change. The issue text
# itself is translated by HA; these labels go into its placeholder, which
# HA does not translate. tests/test_missing_entities.py keeps them in
# sync with translations/*.json.
FIELD_LABELS = {
    "en": {
        "grid_power_entity": "Grid meter",
        "pv_power_entity": "Solar production",
        "battery_soc_entity": "Battery level",
        "battery_charge_power_entity": "Battery charge power",
        "battery_discharge_power_entity": "Battery discharge power",
        "pv_forecast_entity": "PV forecast – remaining today",
        "pv_forecast_today_entity": "PV forecast – hourly data",
        "pv_actual_today_entity": "PV production today in kWh",
        "weather_entity": "Weather forecast",
        "price_entity": "Electricity price sensor",
        "price_level_entity": "Price level sensor",
        "cheap_period_entity": "Cheap price period sensor",
        "cheap_period_starts_in_entity": "Cheap period countdown",
        "switch_entity": "Smart plug / switch",
        "power_entity": "Power measurement",
        "condition_entity": "Run condition sensor",
    },
    "de": {
        "grid_power_entity": "Netzzähler",
        "pv_power_entity": "PV-Erzeugung",
        "battery_soc_entity": "Batterie-Ladestand",
        "battery_charge_power_entity": "Batterie-Ladeleistung",
        "battery_discharge_power_entity": "Batterie-Entladeleistung",
        "pv_forecast_entity": "PV-Prognose – Verbleibend heute",
        "pv_forecast_today_entity": "PV-Prognose – Stundendaten",
        "pv_actual_today_entity": "PV-Erzeugung heute in kWh",
        "weather_entity": "Wettervorhersage",
        "price_entity": "Strompreis-Sensor",
        "price_level_entity": "Preisstufen-Sensor",
        "cheap_period_entity": "Sensor für günstige Preisphase",
        "cheap_period_starts_in_entity": "Countdown bis zur günstigen Phase",
        "switch_entity": "Smarte Steckdose / Schalter",
        "power_entity": "Verbrauchsmessung",
        "condition_entity": "Bedingungs-Sensor",
    },
}


def _entity_id(value):
    """The entity ID of a config field, or None when the field is empty."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def configured_entities(config):
    """Every entity the config refers to, as dicts with entity, device
    (the device name, None for a hub field) and field. Empty fields, and
    a run condition sensor without a limit, are skipped."""
    refs = []
    for field in HUB_FIELDS:
        entity = _entity_id(config.get(field))
        if entity:
            refs.append({"entity": entity, "device": None, "field": field})
    for dev in config.get("devices") or []:
        for field in DEVICE_FIELDS:
            # A run condition without a limit is ignored
            # (DeviceManager._condition_met), so its sensor has no effect.
            if (field == "condition_entity"
                    and dev.get("condition_value") is None):
                continue
            entity = _entity_id(dev.get(field))
            if entity:
                refs.append({"entity": entity,
                             "device": dev.get("name") or "?",
                             "field": field})
    return refs


def describe(ref, lang="en", code=True):
    """One reported entity: 'Washer – Power measurement: `sensor.x`'."""
    labels = FIELD_LABELS.get((lang or "en").split("-")[0].lower(),
                              FIELD_LABELS["en"])
    label = labels.get(ref["field"], ref["field"])
    entity = f"`{ref['entity']}`" if code else ref["entity"]
    if ref["device"] is None:
        return f"{label}: {entity}"
    return f"{ref['device']} – {label}: {entity}"


def format_missing(refs, lang="en"):
    """The repair issue's list of missing entities (Markdown)."""
    return "\n".join(f"- {describe(ref, lang)}" for ref in refs)


class MissingEntityCheck:
    """Tracks which configured entities are missing (see module doc)."""

    CHECK_INTERVAL_S = 300
    CONFIRM_S = 600

    def __init__(self, config):
        self.refs = configured_entities(config)
        self.missing = []        # confirmed refs, in config order
        self._since = {}         # entity -> first check that missed it
        self._last_check = None
        self.first_check = None  # when the first check ran

    def due(self, now):
        """A check is due: the first one, or CHECK_INTERVAL_S after the
        last (also when the clock went back)."""
        if self._last_check is None:
            return True
        elapsed = (now - self._last_check).total_seconds()
        return not 0 <= elapsed < self.CHECK_INTERVAL_S

    def check(self, exists, now):
        """Look up every configured entity with exists(entity_id).
        Returns True when the list of confirmed missing entities
        changed."""
        self._last_check = now
        if self.first_check is None:
            self.first_check = now
        reported = self.missing_entities()
        gone = {ref["entity"] for ref in self.refs
                if not exists(ref["entity"])}
        # min(): a clock that went back restarts the wait.
        self._since = {e: min(self._since.get(e, now), now) for e in gone}
        confirmed = [
            ref for ref in self.refs
            if ref["entity"] in gone and (
                ref["entity"] in reported
                or (now - self._since[ref["entity"]]).total_seconds()
                >= self.CONFIRM_S)]
        changed = confirmed != self.missing
        self.missing = confirmed
        return changed

    def missing_entities(self):
        """The entity IDs of the confirmed missing entities."""
        return {ref["entity"] for ref in self.missing}
