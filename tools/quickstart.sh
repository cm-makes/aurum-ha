#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  AURUM Plug & Play – Quickstart Installer
# ══════════════════════════════════════════════════════════════
#  Run inside Home Assistant OS via the "Advanced SSH & Web Terminal"
#  add-on. Installs:
#   - HACS (official installer)
#   - AURUM integration (from GitHub release)
#   - Mushroom Cards, button-card, auto-entities (HACS frontend deps)
#   - AURUM overlay: configuration.yaml snippets, theme, dashboard
#
#  Safe to re-run: checks before overwriting.
#
#  Usage:
#     wget -O - https://raw.githubusercontent.com/cm-makes/aurum-ha/main/tools/quickstart.sh | bash
# ══════════════════════════════════════════════════════════════

set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-/config}"
WWW_COMMUNITY="$CONFIG_DIR/www/community"
CUSTOM_COMPONENTS="$CONFIG_DIR/custom_components"
OVERLAY_BASE_URL="https://raw.githubusercontent.com/cm-makes/aurum-ha/main/image_overlay/config"
AURUM_RELEASE_API="https://api.github.com/repos/cm-makes/aurum-ha/releases/latest"

log()  { printf "\033[1;33m[AURUM]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;31m[WARN ]\033[0m %s\n" "$*"; }
die()  { warn "$*"; exit 1; }

# ── Pre-flight checks ────────────────────────────────────────
[ -d "$CONFIG_DIR" ] || die "$CONFIG_DIR not found – run this inside the HA SSH add-on."
command -v wget    >/dev/null || die "wget not found"
command -v unzip   >/dev/null || die "unzip not found"
command -v jq      >/dev/null || die "jq not found (try: apk add jq)"

mkdir -p "$CUSTOM_COMPONENTS" "$WWW_COMMUNITY"

# ── 1. HACS ──────────────────────────────────────────────────
if [ -d "$CUSTOM_COMPONENTS/hacs" ]; then
  log "HACS already present → skipping install"
else
  log "Installing HACS..."
  wget -qO - https://get.hacs.xyz | bash -
fi

# ── 2. AURUM integration ────────────────────────────────────
install_gh_zip_to() {
  # $1 = github owner/repo, $2 = target dir, $3 = subfolder in archive (or "")
  local repo="$1" dest="$2" subfolder="${3:-}"
  local tmp
  tmp=$(mktemp -d)
  log "  → Fetching latest release of $repo..."
  local asset_url
  asset_url=$(wget -qO - "https://api.github.com/repos/$repo/releases/latest" \
              | jq -r '.zipball_url // .tarball_url')
  [ "$asset_url" = "null" ] && die "Could not find latest release of $repo"
  wget -qO "$tmp/src.zip" "$asset_url"
  unzip -q "$tmp/src.zip" -d "$tmp"
  local extracted
  extracted=$(find "$tmp" -maxdepth 1 -type d ! -path "$tmp" | head -1)
  if [ -n "$subfolder" ] && [ -d "$extracted/$subfolder" ]; then
    rm -rf "$dest"
    cp -r "$extracted/$subfolder" "$dest"
  else
    rm -rf "$dest"
    cp -r "$extracted" "$dest"
  fi
  rm -rf "$tmp"
}

if [ -d "$CUSTOM_COMPONENTS/aurum" ]; then
  log "AURUM integration already present → skipping (manage via HACS)"
else
  log "Installing AURUM integration..."
  install_gh_zip_to "cm-makes/aurum-ha" "$CUSTOM_COMPONENTS/aurum" "custom_components/aurum"
fi

# ── 3. Frontend deps (Mushroom, button-card, auto-entities) ─
install_lovelace_plugin() {
  # $1 = github owner/repo, $2 = js filename within archive dist
  local repo="$1" jsname="$2" plugin_name
  plugin_name=$(basename "$repo")
  local target="$WWW_COMMUNITY/$plugin_name"
  if [ -d "$target" ]; then
    log "Frontend plugin $plugin_name already present → skipping"
    return
  fi
  log "Installing frontend plugin $plugin_name..."
  install_gh_zip_to "$repo" "$target" ""
}

install_lovelace_plugin "piitaya/lovelace-mushroom"   "mushroom.js"
install_lovelace_plugin "custom-cards/button-card"    "button-card.js"
install_lovelace_plugin "thomasloven/lovelace-auto-entities" "auto-entities.js"

# ── 4. Overlay: configuration.yaml snippets + theme + dashboard ──
overlay_fetch() {
  local rel_path="$1"
  local target="$CONFIG_DIR/$rel_path"
  mkdir -p "$(dirname "$target")"
  if [ -e "$target" ] && ! [ -L "$target" ] && [ -z "${AURUM_FORCE:-}" ]; then
    log "  ↓ $rel_path already exists → keeping user version (set AURUM_FORCE=1 to overwrite)"
    return
  fi
  log "  ↓ $rel_path"
  wget -qO "$target" "$OVERLAY_BASE_URL/$rel_path"
}

log "Deploying AURUM overlay files..."
overlay_fetch "themes/aurum-dark.yaml"
overlay_fetch "packages/aurum_defaults.yaml"
overlay_fetch "dashboards/aurum.yaml"

# ── configuration.yaml merge (manual step if file exists) ──
if [ -s "$CONFIG_DIR/configuration.yaml" ] && grep -q "default_config:" "$CONFIG_DIR/configuration.yaml"; then
  log "configuration.yaml already has default_config → leaving alone."
  log "Check docs/QUICKSTART.md for required additions (themes, packages, dashboards)."
else
  log "Writing minimal configuration.yaml..."
  wget -qO "$CONFIG_DIR/configuration.yaml" "$OVERLAY_BASE_URL/configuration.yaml"
fi

# ── 5. Lovelace resource registration ────────────────────────
# (resources are auto-detected in storage mode, but we pre-register to be safe)
RESOURCES_FILE="$CONFIG_DIR/.storage/lovelace_resources"
if [ ! -f "$RESOURCES_FILE" ]; then
  log "No lovelace_resources file found → HA will discover HACS resources on restart."
fi

# ── Done ─────────────────────────────────────────────────────
cat <<EOF

══════════════════════════════════════════════════════════════
  AURUM Plug & Play Installation complete!
══════════════════════════════════════════════════════════════

Next steps:

  1. Einstellungen → System → Neustart → Home Assistant
  2. Nach Neustart: Einstellungen → Integrationen →
     Inverter hinzufügen (Fronius / SMA / Kostal / SolarEdge)
     Smart-Plug-Integration hinzufügen (Shelly / Tasmota)
  3. Einstellungen → Integrationen → + AURUM hinzufügen
  4. AURUM-Dashboard erscheint in der Seitenleiste

  Ausführliche Anleitung:
    https://github.com/cm-makes/aurum-ha/blob/main/docs/QUICKSTART.md

══════════════════════════════════════════════════════════════
EOF
