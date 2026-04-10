"""AURUM – Constants and configuration keys."""

DOMAIN = "aurum"
VERSION = "1.7.4"

PLATFORMS = ["sensor", "binary_sensor", "number", "switch", "time"]

# ── Config keys: Energy sources (Step 1) ─────────────────────────
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_PV_POWER_ENTITY = "pv_power_entity"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_BATTERY_CHARGE_POWER_ENTITY = "battery_charge_power_entity"
CONF_BATTERY_DISCHARGE_POWER_ENTITY = "battery_discharge_power_entity"

# ── Config keys: PV Forecast / Budget (optional) ─────────────────
CONF_PV_FORECAST_ENTITY = "pv_forecast_entity"
CONF_PV_FORECAST_TODAY_ENTITY = "pv_forecast_today_entity"
CONF_PV_ACTUAL_TODAY_ENTITY = "pv_actual_today_entity"
CONF_WEATHER_ENTITY = "weather_entity"

# ── Config keys: Battery settings (Step 2) ───────────────────────
CONF_BATTERY_CAPACITY_WH = "battery_capacity_wh"
CONF_TARGET_SOC = "target_soc"
CONF_MIN_SOC = "min_soc"
CONF_UPDATE_INTERVAL = "update_interval"

# ── Config keys: Notifications ──────────────────────────────────
CONF_NOTIFY_SERVICE = "notify_service"

# ── Config keys: Price-aware scheduling (optional) ──────────────
CONF_PRICE_ENTITY = "price_entity"
CONF_PRICE_LEVEL_ENTITY = "price_level_entity"
CONF_CHEAP_PERIOD_ENTITY = "cheap_period_entity"
CONF_CHEAP_PERIOD_STARTS_IN_ENTITY = "cheap_period_starts_in_entity"

# ── Config keys: Devices (Options Flow) ──────────────────────────
CONF_DEVICES = "devices"

# ── Defaults ─────────────────────────────────────────────────────
DEFAULT_BATTERY_CAPACITY_WH = 5000
DEFAULT_TARGET_SOC = 80
DEFAULT_MIN_SOC = 10
DEFAULT_UPDATE_INTERVAL = 15

# ── Device config keys ───────────────────────────────────────────
CONF_DEV_NAME = "name"
CONF_DEV_SWITCH_ENTITY = "switch_entity"
CONF_DEV_POWER_ENTITY = "power_entity"
CONF_DEV_NOMINAL_POWER = "nominal_power"
CONF_DEV_PRIORITY = "priority"
CONF_DEV_SOC_THRESHOLD = "soc_threshold"
CONF_DEV_STARTUP_DETECTION = "startup_detection"
CONF_DEV_HYSTERESIS_ON = "hysteresis_on"
CONF_DEV_HYSTERESIS_OFF = "hysteresis_off"
CONF_DEV_DEBOUNCE_ON = "debounce_on"
CONF_DEV_DEBOUNCE_OFF = "debounce_off"
CONF_DEV_MIN_ON_TIME = "min_on_time"
CONF_DEV_MIN_OFF_TIME = "min_off_time"
CONF_DEV_DEADLINE = "deadline"
CONF_DEV_ESTIMATED_RUNTIME = "estimated_runtime"
CONF_DEV_INTERRUPTIBLE = "interruptible"
CONF_DEV_MANUAL_OVERRIDE_ENTITY = "manual_override_entity"
CONF_DEV_MUSS_HEUTE_ENTITY = "muss_heute_entity"
CONF_DEV_RESIDUAL_POWER = "residual_power"

# ── Device config keys: Price-aware scheduling ──────────────────
CONF_DEV_PRICE_MODE = "price_mode"
CONF_DEV_MAX_PRICE = "max_price"

# ── Price modes ─────────────────────────────────────────────────
PRICE_MODE_SOLAR_ONLY = "solar_only"
PRICE_MODE_CHEAP_GRID = "cheap_grid"

# ── Device config keys: Startup Detection ────────────────────────
CONF_DEV_SD_POWER_THRESHOLD = "sd_power_threshold"
CONF_DEV_SD_DETECTION_TIME = "sd_detection_time"
CONF_DEV_SD_STANDBY_POWER = "sd_standby_power"
CONF_DEV_SD_FINISH_POWER = "sd_finish_power"
CONF_DEV_SD_FINISH_TIME = "sd_finish_time"
CONF_DEV_SD_MAX_RUNTIME = "sd_max_runtime"

# ── Device defaults ──────────────────────────────────────────────
DEFAULT_DEV_NOMINAL_POWER = 1000
DEFAULT_DEV_PRIORITY = 50
DEFAULT_DEV_SOC_THRESHOLD = 20
DEFAULT_DEV_HYSTERESIS_ON = 200
DEFAULT_DEV_HYSTERESIS_OFF = 100
DEFAULT_DEV_DEBOUNCE_ON = 300
DEFAULT_DEV_DEBOUNCE_OFF = 600
DEFAULT_DEV_MIN_ON_TIME = 600
DEFAULT_DEV_MIN_OFF_TIME = 60
DEFAULT_DEV_RESIDUAL_POWER = 100

# ── Device defaults: Startup Detection ───────────────────────────
DEFAULT_DEV_SD_POWER_THRESHOLD = 5
DEFAULT_DEV_SD_DETECTION_TIME = 5
DEFAULT_DEV_SD_STANDBY_POWER = 3
DEFAULT_DEV_SD_FINISH_POWER = 3
DEFAULT_DEV_SD_FINISH_TIME = 600
DEFAULT_DEV_SD_MAX_RUNTIME = 10800

# ── Battery modes ────────────────────────────────────────────────
MODE_NORMAL = "normal"
MODE_LOW_SOC = "low_soc"
MODE_CHARGING = "charging"

# ── Device states ────────────────────────────────────────────────
DEVICE_ACTIVE_STATES = ("on", "running", "manual_override")

# ── Startup Detection states ─────────────────────────────────────
SD_STATE_STANDBY = "standby"
SD_STATE_DETECTED = "detected"
SD_STATE_WAITING = "waiting"
SD_STATE_RUNNING = "running"
SD_STATE_DONE = "done"

# ── Deficit tolerance timers ────────────────────────────────────
DEFAULT_EXCESS_DEFICIT_TOLERANCE = 60   # seconds
DEFAULT_SOC_GRID_DEFICIT_TOLERANCE = 90  # seconds


# ── Auto-switch entity ID helpers ────────────────────────────────
def override_entity_id(slug: str) -> str:
    """Return the deterministic entity_id for the manual override switch."""
    return f"switch.aurum_{slug}_override"


def muss_heute_entity_id(slug: str) -> str:
    """Return the deterministic entity_id for the 'must run today' switch."""
    return f"switch.aurum_{slug}_muss_heute"
