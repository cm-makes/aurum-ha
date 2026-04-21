# AURUM Image Overlay

Files in this folder are meant to be dropped into a fresh Home Assistant OS
installation's `/config/` directory to bootstrap a ready-to-use AURUM setup.
Used by `tools/quickstart.sh` and (later) the full SD card image builder.

## Contents

| Path | Purpose |
|---|---|
| `config/configuration.yaml` | Enables `default_config`, packages folder, custom theme |
| `config/themes/aurum-dark.yaml` | Dark theme, gold/amber accents |
| `config/packages/aurum_defaults.yaml` | Sensible defaults (timer helpers, device presets) |
| `config/dashboards/aurum.yaml` | Pre-built lovelace dashboard using only `sensor.aurum_*` entities |

## Design Principles

1. **No personal data** — all entity references use the `sensor.aurum_*` pattern
   that AURUM creates itself, never a vendor-specific ID like `sensor.fronius_*`.
2. **Additive only** — nothing here modifies HA core files. If the user has
   existing config, these files co-exist.
3. **Works pre-AURUM-setup** — templates use `| float(0)` defaults so the
   dashboard renders even when entities are still `unknown`.

## Usage

The `tools/quickstart.sh` installer copies these files into `/config/` after
installing HACS, AURUM, Mushroom Cards, and button-card.
