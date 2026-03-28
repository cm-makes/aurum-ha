"""AURUM – Constants and configuration keys."""

DOMAIN = "aurum"
VERSION = "1.0.0"

PLATFORMS = ["sensor", "binary_sensor", "number"]

# ── Config keys: Energy sources (Step 1) ─────────────────────────
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_PV_POWER_ENTITY = "pv_power_entity"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"

# ── Config keys: Battery settings (Step 2) ───────────────────────
CONF_BATTERY_CAPACITY_WH = "battery_capacity_wh"
CONF_TARGET_SOC = "target_soc"
CONF_MIN_SOC = "min_soc"
CONF_UPDATE_INTERVAL = "update_interval"

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

# ── Battery modes ────────────────────────────────────────────────
MODE_NORMAL = "normal"
MODE_LOW_SOC = "low_soc"
MODE_CHARGING = "charging"

# ── Device states ────────────────────────────────────────────────
DEVICE_ACTIVE_STATES = ("on", "running", "manual_override")

# ── Startup Detection states ─────────────────────────────────────
SD_STATE_STANDBY = "standby"
SD_STATE_DETECTED = "detected"
SD_STATE_RUNNING = "running"
SD_STATE_DONE = "done"
