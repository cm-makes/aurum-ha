/*
 * AURUM – Dashboard Panel
 * =======================
 * A dependency-free custom sidebar panel that renders live from the
 * AURUM entities Home Assistant already creates. It discovers devices
 * from the per-device override switches (switch.aurum_<slug>_override)
 * and builds all other entity_ids deterministically from the slug, so
 * adding or removing a device in the AURUM config is reflected here
 * automatically — no dashboard editing required.
 *
 * Pure vanilla JS (no build step, no Lit) so it ships as-is via HACS.
 */

const HUB = {
  pv: "sensor.aurum_pv_power",
  grid: "sensor.aurum_grid_power",
  soc: "sensor.aurum_battery_soc",
  surplus: "sensor.aurum_excess_power",
  budget: "sensor.aurum_budget",
  house: "sensor.aurum_house_consumption",
  forecast: "sensor.aurum_forecast_remaining",
  cheap: "binary_sensor.aurum_cheap_grid_active",
  advisor: "sensor.aurum_current_decision",
};

// Advisor decision code → banner icon + accent color.
const DECISION_META = {
  startup: { icon: "⏳", color: "var(--secondary-text-color,#888)" },
  battery_charging: { icon: "🔋", color: "#ffb300" },
  running_solar: { icon: "☀️", color: "var(--success-color,#43a047)" },
  running_cheap_grid: { icon: "💶", color: "#ffb300" },
  running: { icon: "▶️", color: "var(--success-color,#43a047)" },
  waiting: { icon: "⌛", color: "var(--secondary-text-color,#888)" },
  idle: { icon: "💤", color: "var(--secondary-text-color,#888)" },
  unknown: { icon: "❔", color: "var(--secondary-text-color,#888)" },
};

// Per-device entity_id suffixes, all derived from the device slug.
const DEV = (slug) => ({
  status: `sensor.aurum_${slug}`,
  power: `sensor.aurum_${slug}_power`,
  runtime: `sensor.aurum_${slug}_runtime`,
  energy: `sensor.aurum_${slug}_energy_today`,
  active: `binary_sensor.aurum_${slug}_active`,
  override: `switch.aurum_${slug}_override`,
  mussHeute: `switch.aurum_${slug}_muss_heute`,
  disable: `switch.aurum_${slug}_disable`,
  socThreshold: `number.aurum_${slug}_soc_threshold`,
  maxPrice: `number.aurum_${slug}_max_price`,
  pvThreshold: `number.aurum_${slug}_pv_power_threshold`,
  deadline: `time.aurum_${slug}_deadline`,
});

const STATE_COLOR = {
  running: "var(--success-color, #43a047)",
  on: "var(--success-color, #43a047)",
  waiting: "var(--warning-color, #ffa600)",
  standby: "var(--warning-color, #ffa600)",
  detected: "var(--warning-color, #ffa600)",
  done: "var(--secondary-text-color, #888)",
  off: "var(--secondary-text-color, #888)",
  disabled: "var(--error-color, #db4437)",
};

// UI strings — English default, German when the HA UI language is de.
// Mirrors the integration's notification localization (en/de parity).
const STRINGS = {
  en: {
    solar: "Solar", grid: "Grid", battery: "Battery", surplus: "Surplus",
    budget: "Budget", house: "House", forecast: "Left today", cheap: "Cheap grid",
    cheapActive: "active", devices: "Devices",
    empty: "No devices configured yet. Add one in the AURUM options " +
      "(Settings → Integrations → AURUM → Configure) — it will show up " +
      "here automatically.",
    modePV: "PV", modeManual: "Manual", modeOff: "Off",
    modePVTitle: "AURUM controls the device from PV surplus automatically",
    modeManualTitle: "AURUM pauses — you control the device yourself",
    modeOffTitle: "Device stays off (force-off)",
    mussHeute: "Must run today",
    mussHeuteTitle: "Activate the deadline — the device will finish today",
    socThreshold: "SOC threshold", maxPrice: "Max price (ct/kWh)",
    pvThreshold: "Solar power ≥ (W)",
    deadline: "Finish by", stateOff: "off",
    devicesOn: "active",
    // Advisor decision headline — FALLBACK ONLY. The banner prefers
    // hass.formatEntityState() (backend translations, all HA languages);
    // these strings only render on older HA frontends without it.
    decision_startup: "Starting up",
    decision_battery_charging: "Charging battery – devices paused",
    decision_running_solar: "Running on solar surplus",
    decision_running_cheap_grid: "Running on cheap grid power",
    decision_running: "Devices running",
    decision_waiting: "Waiting for surplus",
    decision_idle: "Idle – no devices",
    decision_unknown: "Unknown",
    // Advisor per-device reason codes (attributes – no backend translation)
    reason_solar_surplus: "solar surplus",
    reason_solar_pv: "solar power ≥ threshold",
    reason_cheap_grid: "cheap grid power",
    reason_manual_override: "manual override",
    reason_forced_deadline: "deadline start",
    reason_running: "running",
    reason_runtime_done: "daily runtime reached",
    reason_program_done: "program finished",
    reason_program_paused: "program paused",
    reason_program_standby: "waiting for program start",
    reason_battery_charging: "battery charging",
    reason_below_soc_threshold: "battery below threshold",
    reason_condition_not_met: "run condition not met",
    reason_disabled: "disabled (force-off)",
    reason_waiting_surplus: "waiting for surplus",
  },
  de: {
    solar: "Solar", grid: "Netz", battery: "Akku", surplus: "Überschuss",
    budget: "Budget", house: "Haus", forecast: "Rest heute", cheap: "Günstig",
    cheapActive: "aktiv", devices: "Geräte",
    empty: "Noch keine Geräte konfiguriert. Füge in den AURUM-Einstellungen " +
      "ein Gerät hinzu – es erscheint dann hier automatisch.",
    modePV: "PV", modeManual: "Manuell", modeOff: "Aus",
    modePVTitle: "AURUM steuert automatisch nach PV-Überschuss",
    modeManualTitle: "AURUM pausiert – du steuerst das Gerät selbst",
    modeOffTitle: "Gerät bleibt aus (Force-Off)",
    mussHeute: "Muss heute",
    mussHeuteTitle: "Deadline aktivieren – Gerät läuft heute auf jeden Fall",
    socThreshold: "SOC-Schwelle", maxPrice: "Max. Preis (ct/kWh)",
    pvThreshold: "Solarleistung ≥ (W)",
    deadline: "Fertig bis", stateOff: "aus",
    devicesOn: "aktiv",
    // Advisor-Entscheidung — NUR FALLBACK (siehe EN-Kommentar).
    decision_startup: "Startet …",
    decision_battery_charging: "Batterie lädt – Geräte pausiert",
    decision_running_solar: "Läuft mit Solar-Überschuss",
    decision_running_cheap_grid: "Läuft mit günstigem Netzstrom",
    decision_running: "Geräte laufen",
    decision_waiting: "Wartet auf Überschuss",
    decision_idle: "Leerlauf – keine Geräte",
    decision_unknown: "Unbekannt",
    // Advisor-Begründungen pro Gerät (Attribute – keine Backend-Übersetzung)
    reason_solar_surplus: "Solar-Überschuss",
    reason_solar_pv: "Solarleistung ≥ Schwelle",
    reason_cheap_grid: "günstiger Netzstrom",
    reason_manual_override: "manuell übersteuert",
    reason_forced_deadline: "Deadline-Start",
    reason_running: "läuft",
    reason_runtime_done: "Tageslaufzeit erreicht",
    reason_program_done: "Programm fertig",
    reason_program_paused: "Programm pausiert",
    reason_program_standby: "wartet auf Programmstart",
    reason_battery_charging: "Batterie lädt",
    reason_below_soc_threshold: "Akku unter Schwelle",
    reason_condition_not_met: "Bedingung nicht erfüllt",
    reason_disabled: "deaktiviert (Aus-Schalter)",
    reason_waiting_surplus: "wartet auf Überschuss",
  },
};

class AurumPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._sig = null; // structural signature (device slugs)
    this._refs = {}; // id -> update fn
    this._advReasons = null; // slug -> advisor reason (memo per update)
  }

  set hass(hass) {
    this._hass = hass;
    this._sync();
  }
  set narrow(_v) {}
  set route(_v) {}
  set panel(_v) {}

  connectedCallback() {
    this._sync();
  }

  // ── Data helpers ─────────────────────────────────────────────
  _st(entityId) {
    const s = this._hass && this._hass.states[entityId];
    return s ? s.state : null;
  }
  _attr(entityId, attr) {
    const s = this._hass && this._hass.states[entityId];
    return s && s.attributes ? s.attributes[attr] : undefined;
  }
  _exists(entityId) {
    return !!(this._hass && this._hass.states[entityId]);
  }

  _lang() {
    const l =
      (this._hass &&
        ((this._hass.locale && this._hass.locale.language) ||
          this._hass.language)) ||
      "en";
    return String(l).toLowerCase().startsWith("de") ? "de" : "en";
  }

  _t(key) {
    return (STRINGS[this._lang()] || STRINGS.en)[key] || STRINGS.en[key] || key;
  }

  _devices() {
    if (!this._hass) return [];
    const out = [];
    for (const id of Object.keys(this._hass.states)) {
      // Match switch.aurum_<slug>_override → one per device.
      const m = /^switch\.aurum_(.+)_override$/.exec(id);
      if (!m) continue;
      const slug = m[1];
      const e = DEV(slug);
      const st = this._hass.states[e.status];
      let name = slug;
      if (st && st.attributes && st.attributes.friendly_name) {
        name = st.attributes.friendly_name.replace(/^AURUM\s+/, "");
      }
      out.push({ slug, name, e });
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
  }

  _callService(domain, service, data) {
    if (!this._hass) return;
    // Surface rejected calls (entity missing, value out of range) instead
    // of leaving unhandled promise rejections with zero user feedback.
    Promise.resolve(this._hass.callService(domain, service, data)).catch(
      (err) => console.warn("AURUM panel: service call failed", domain, service, data, err)
    );
  }

  // ── Render orchestration ─────────────────────────────────────
  _sync() {
    if (!this._hass) return;
    const devices = this._devices();
    // Structural signature: rebuild not only when the device set changes,
    // but also when a device's name resolves or its optional control
    // entities (muss_heute / sliders / deadline) register later — during
    // HA startup the override switch can appear before the rest.
    const sig = JSON.stringify([
      this._lang(), // rebuild with new labels if the UI language changes
      this._exists(HUB.advisor), // banner appears when the sensor registers
      devices.map((d) => [
        d.slug,
        d.name,
        this._exists(d.e.mussHeute),
        this._exists(d.e.socThreshold),
        this._exists(d.e.maxPrice),
        this._exists(d.e.pvThreshold),
        this._exists(d.e.deadline),
      ]),
    ]);
    if (sig !== this._sig) {
      this._sig = sig;
      this._build(devices);
    }
    this._update(devices);
  }

  _build(devices) {
    this._refs = {};
    this._advReasons = null;
    this.innerHTML = "";

    const style = document.createElement("style");
    style.textContent = CSS;
    this.appendChild(style);

    const root = document.createElement("div");
    root.className = "aurum-root";
    this.appendChild(root);

    // Header
    const header = document.createElement("div");
    header.className = "aurum-header";
    header.innerHTML =
      '<div class="aurum-title">☀️ AURUM</div>' +
      '<div class="aurum-sub">Solar Surplus Optimizer</div>';
    root.appendChild(header);

    // Advisor banner: what AURUM is doing right now, and why.
    // Hidden entirely on installs that predate the advisor sensor.
    if (this._exists(HUB.advisor)) root.appendChild(this._buildAdvisor());

    // Overview chips
    root.appendChild(this._buildOverview());

    // Devices
    const devWrap = document.createElement("div");
    devWrap.className = "aurum-section";
    const h = document.createElement("div");
    h.className = "aurum-section-title";
    h.textContent = this._t("devices");
    devWrap.appendChild(h);

    if (!devices.length) {
      const empty = document.createElement("div");
      empty.className = "aurum-empty";
      empty.textContent = this._t("empty");
      devWrap.appendChild(empty);
    } else {
      const grid = document.createElement("div");
      grid.className = "aurum-devgrid";
      for (const d of devices) grid.appendChild(this._buildDeviceCard(d));
      devWrap.appendChild(grid);
    }
    root.appendChild(devWrap);
  }

  // Translate an advisor reason code; fall back to the raw code so new
  // backend vocabulary still renders (untranslated) instead of vanishing.
  _reasonText(code) {
    if (!code) return "";
    const key = "reason_" + code;
    const lang = STRINGS[this._lang()] || STRINGS.en;
    return lang[key] || STRINGS.en[key] || code;
  }

  _buildAdvisor() {
    const box = document.createElement("div");
    box.className = "aurum-advisor";
    const icon = document.createElement("div");
    icon.className = "aurum-advisor-icon";
    const body = document.createElement("div");
    body.className = "aurum-advisor-body";
    const head = document.createElement("div");
    head.className = "aurum-advisor-head";
    const sub = document.createElement("div");
    sub.className = "aurum-advisor-sub";
    body.appendChild(head);
    body.appendChild(sub);
    box.appendChild(icon);
    box.appendChild(body);

    this._refs["advisor"] = () => {
      let code = this._st(HUB.advisor) || "unknown";
      if (code === "unavailable") code = "unknown";
      const meta = DECISION_META[code] || DECISION_META.unknown;
      icon.textContent = meta.icon;
      box.style.borderLeftColor = meta.color;

      // Headline: prefer HA's backend-localized ENUM state (covers every
      // HA language); fall back to the local mirror on older frontends.
      let headline = "";
      const stObj = this._hass && this._hass.states[HUB.advisor];
      if (stObj && typeof this._hass.formatEntityState === "function") {
        try {
          headline = this._hass.formatEntityState(stObj);
        } catch (_e) { /* fall back below */ }
      }
      if (!headline || headline === code) {
        const lang = STRINGS[this._lang()] || STRINGS.en;
        headline =
          lang["decision_" + code] || STRINGS.en["decision_" + code] || code;
      }
      head.textContent = headline;

      // Memo for the device cards: slug → reason (built once per update
      // pass; this updater runs before the card updaters by insertion
      // order). Cleared in _build.
      this._advReasons = null;
      const advDevs = this._attr(HUB.advisor, "devices");
      if (Array.isArray(advDevs)) {
        this._advReasons = new Map();
        for (const x of advDevs) {
          if (x && x.slug) this._advReasons.set(x.slug, x.reason);
        }
      }

      // Context line: devices active · surplus (live sensor) · price.
      const parts = [];
      const on = this._attr(HUB.advisor, "devices_on");
      const total = this._attr(HUB.advisor, "devices_total");
      if (on != null && total != null)
        parts.push(`${on}/${total} ${this._t("devicesOn")}`);
      const ex = parseFloat(this._st(HUB.surplus));
      if (!isNaN(ex)) parts.push(`⚡ ${Math.round(ex)} W`);
      const ct = this._attr(HUB.advisor, "current_price_ct");
      if (ct != null) parts.push(`💶 ${ct} ct/kWh`);
      sub.textContent = parts.join(" · ");
    };
    return box;
  }

  _buildOverview() {
    const sec = document.createElement("div");
    sec.className = "aurum-overview";
    const add = (key, icon, label, fmt) => {
      const chip = document.createElement("div");
      chip.className = "aurum-chip";
      const ic = document.createElement("div");
      ic.className = "aurum-chip-icon";
      ic.textContent = icon;
      const body = document.createElement("div");
      const val = document.createElement("div");
      val.className = "aurum-chip-value";
      const lab = document.createElement("div");
      lab.className = "aurum-chip-label";
      lab.textContent = label;
      body.appendChild(val);
      body.appendChild(lab);
      chip.appendChild(ic);
      chip.appendChild(body);
      sec.appendChild(chip);
      this._refs["ov_" + key] = () => {
        const r = fmt();
        val.textContent = r.text;
        if (r.color) ic.style.color = r.color;
      };
    };

    add("pv", "🔆", this._t("solar"), () => {
      const v = parseFloat(this._st(HUB.pv));
      return { text: isNaN(v) ? "–" : `${Math.round(v)} W`, color: "#ffb300" };
    });
    add("grid", "🔌", this._t("grid"), () => {
      const v = parseFloat(this._st(HUB.grid));
      if (isNaN(v)) return { text: "–" };
      if (v > 50)
        return { text: `↓ ${Math.round(v)} W`, color: "var(--error-color,#db4437)" };
      if (v < -50)
        return {
          text: `↑ ${Math.round(Math.abs(v))} W`,
          color: "var(--success-color,#43a047)",
        };
      return { text: "≈ 0 W", color: "var(--secondary-text-color,#888)" };
    });
    add("soc", "🔋", this._t("battery"), () => {
      const v = parseFloat(this._st(HUB.soc));
      if (isNaN(v) || v < 0) return { text: "–", color: "var(--secondary-text-color,#888)" };
      const color = v >= 60 ? "var(--success-color,#43a047)" : v >= 30 ? "#ffb300" : "var(--error-color,#db4437)";
      return { text: `${Math.round(v)} %`, color };
    });
    add("surplus", "⚡", this._t("surplus"), () => {
      const v = parseFloat(this._st(HUB.surplus));
      if (isNaN(v)) return { text: "–" };
      const color = v > 500 ? "var(--success-color,#43a047)" : v > 100 ? "#ffb300" : "var(--secondary-text-color,#888)";
      return { text: `${Math.round(v)} W`, color };
    });
    add("budget", "🎯", this._t("budget"), () => {
      const v = parseFloat(this._st(HUB.budget));
      return { text: isNaN(v) ? "∞" : `${Math.round(v)} W` };
    });
    add("house", "🏠", this._t("house"), () => {
      const v = parseFloat(this._st(HUB.house));
      return { text: isNaN(v) ? "–" : `${Math.round(v)} W` };
    });
    add("forecast", "📈", this._t("forecast"), () => {
      const v = parseFloat(this._st(HUB.forecast));
      return { text: isNaN(v) ? "–" : `${v.toFixed(1)} kWh` };
    });
    add("cheap", "💶", this._t("cheap"), () => {
      const on = this._st(HUB.cheap) === "on";
      return {
        text: on ? this._t("cheapActive") : "–",
        color: on ? "#ffb300" : "var(--secondary-text-color,#888)",
      };
    });
    return sec;
  }

  _buildDeviceCard(d) {
    const e = d.e;
    const card = document.createElement("div");
    card.className = "aurum-card";

    // Header row: name + state badge
    const top = document.createElement("div");
    top.className = "aurum-card-top";
    const nm = document.createElement("div");
    nm.className = "aurum-card-name";
    nm.textContent = d.name;
    const badge = document.createElement("span");
    badge.className = "aurum-badge";
    top.appendChild(nm);
    top.appendChild(badge);
    card.appendChild(top);

    // Metrics line
    const metrics = document.createElement("div");
    metrics.className = "aurum-metrics";
    card.appendChild(metrics);

    // Reason line
    const reason = document.createElement("div");
    reason.className = "aurum-reason";
    card.appendChild(reason);

    // Mode selector: PV (auto) | Manuell (override) | Aus (disable).
    // Clearer than raw switch names — one segmented control, one active mode.
    const ctl = document.createElement("div");
    ctl.className = "aurum-controls";

    const seg = document.createElement("div");
    seg.className = "aurum-seg";
    const mkMode = (label, title, onClick) => {
      const b = document.createElement("button");
      b.className = "aurum-seg-btn";
      b.textContent = label;
      b.title = title;
      b.addEventListener("click", onClick);
      seg.appendChild(b);
      return b;
    };
    const svc = (service, entity) => {
      if (!this._exists(entity)) return;
      this._callService("switch", service, { entity_id: entity });
    };
    const mPV = mkMode(this._t("modePV"), this._t("modePVTitle"), () => {
      svc("turn_off", e.override);
      svc("turn_off", e.disable);
    });
    const mManual = mkMode(this._t("modeManual"), this._t("modeManualTitle"), () => {
      svc("turn_on", e.override);
      svc("turn_off", e.disable);
    });
    const mOff = mkMode(this._t("modeOff"), this._t("modeOffTitle"), () => {
      svc("turn_off", e.override);
      svc("turn_on", e.disable);
    });
    ctl.appendChild(seg);

    // "Muss heute" stays a separate toggle: it augments the mode
    // (activates the deadline) rather than replacing it.
    let tMuss = null;
    if (this._exists(e.mussHeute)) {
      tMuss = document.createElement("button");
      tMuss.className = "aurum-toggle";
      tMuss.textContent = this._t("mussHeute");
      tMuss.title = this._t("mussHeuteTitle");
      tMuss.addEventListener("click", () =>
        this._callService("switch", "toggle", { entity_id: e.mussHeute })
      );
      ctl.appendChild(tMuss);
    }
    card.appendChild(ctl);

    // Sliders / inputs
    const inputs = document.createElement("div");
    inputs.className = "aurum-inputs";

    let socInput = null;
    let socVal = null;
    if (this._exists(e.socThreshold)) {
      const row = document.createElement("label");
      row.className = "aurum-input-row";
      const lab = document.createElement("span");
      lab.textContent = this._t("socThreshold");
      socVal = document.createElement("span");
      socVal.className = "aurum-input-val";
      socInput = document.createElement("input");
      socInput.type = "range";
      socInput.min = "0";
      socInput.max = "100";
      socInput.step = "5";
      socInput.addEventListener("change", () =>
        this._callService("number", "set_value", {
          entity_id: e.socThreshold,
          value: Number(socInput.value),
        })
      );
      socInput.addEventListener("input", () => {
        if (socVal) socVal.textContent = `${socInput.value} %`;
      });
      const head = document.createElement("div");
      head.className = "aurum-input-head";
      head.appendChild(lab);
      head.appendChild(socVal);
      row.appendChild(head);
      row.appendChild(socInput);
      inputs.appendChild(row);
    }

    let priceInput = null;
    if (this._exists(e.maxPrice)) {
      const row = document.createElement("label");
      row.className = "aurum-input-row aurum-input-inline";
      const lab = document.createElement("span");
      lab.textContent = this._t("maxPrice");
      priceInput = document.createElement("input");
      priceInput.type = "number";
      priceInput.min = "0";
      priceInput.max = "100";
      priceInput.step = "1";
      priceInput.className = "aurum-num";
      priceInput.addEventListener("change", () => {
        // Empty/invalid input must NOT silently commit 0 ("never buy grid")
        if (priceInput.value === "") return;
        const v = Math.min(100, Math.max(0, Number(priceInput.value)));
        this._callService("number", "set_value", {
          entity_id: e.maxPrice,
          value: v,
        });
      });
      row.appendChild(lab);
      row.appendChild(priceInput);
      inputs.appendChild(row);
    }

    let pvInput = null;
    if (this._exists(e.pvThreshold)) {
      const row = document.createElement("label");
      row.className = "aurum-input-row aurum-input-inline";
      const lab = document.createElement("span");
      lab.textContent = this._t("pvThreshold");
      pvInput = document.createElement("input");
      pvInput.type = "number";
      pvInput.min = "0";
      pvInput.max = "10000";
      pvInput.step = "50";
      pvInput.className = "aurum-num";
      pvInput.addEventListener("change", () => {
        if (pvInput.value === "") return;
        const v = Math.min(10000, Math.max(0, Number(pvInput.value)));
        this._callService("number", "set_value", {
          entity_id: e.pvThreshold,
          value: v,
        });
      });
      row.appendChild(lab);
      row.appendChild(pvInput);
      inputs.appendChild(row);
    }

    let deadlineInput = null;
    if (this._exists(e.deadline)) {
      const row = document.createElement("label");
      row.className = "aurum-input-row aurum-input-inline";
      const lab = document.createElement("span");
      lab.textContent = this._t("deadline");
      deadlineInput = document.createElement("input");
      deadlineInput.type = "time";
      deadlineInput.className = "aurum-num";
      deadlineInput.addEventListener("change", () =>
        this._callService("time", "set_value", {
          entity_id: e.deadline,
          time: (deadlineInput.value || "00:00") + ":00",
        })
      );
      row.appendChild(lab);
      row.appendChild(deadlineInput);
      inputs.appendChild(row);
    }

    card.appendChild(inputs);

    // Store updater for this card
    this._refs["dev_" + d.slug] = () => {
      let state = (this._st(e.status) || "off").toLowerCase();
      if (state === "unavailable" || state === "unknown") state = "off";
      badge.textContent = state;
      badge.style.background = STATE_COLOR[state] || "var(--secondary-text-color,#888)";

      const disabled = this._st(e.disable) === "on";
      if (disabled) {
        badge.textContent = this._t("stateOff");
        badge.style.background = STATE_COLOR.disabled;
      }

      const parts = [];
      const p = parseFloat(this._st(e.power));
      if (!isNaN(p)) parts.push(`⚡ ${Math.round(p)} W`);
      const rt = parseFloat(this._st(e.runtime));
      if (!isNaN(rt)) parts.push(`⏱ ${rt} min`);
      // Energy sensor reports Wh; honor the unit attribute when present.
      const en = parseFloat(this._st(e.energy));
      if (!isNaN(en)) {
        const unit = this._attr(e.energy, "unit_of_measurement") || "Wh";
        const kwh = unit === "kWh" ? en : en / 1000;
        parts.push(`🔆 ${kwh.toFixed(2)} kWh`);
      }
      metrics.textContent = parts.join("   ");

      // Prefer the advisor's per-device reason (translated, via the memo
      // the banner updater builds); fall back to the raw scheduling_reason
      // attribute on pre-advisor installs.
      let reasonText = "";
      if (this._advReasons && this._advReasons.has(d.slug)) {
        reasonText = this._reasonText(this._advReasons.get(d.slug));
      }
      if (!reasonText) {
        const rs = this._attr(e.status, "scheduling_reason");
        if (rs) reasonText = rs;
      }
      reason.textContent = reasonText ? `→ ${reasonText}` : "";

      // Derive the active mode: Aus (disable) beats Manuell (override),
      // matching the backend priority in devices.py.
      const isDisabled = this._st(e.disable) === "on";
      const isOverride = this._st(e.override) === "on";
      mPV.classList.toggle("active", !isDisabled && !isOverride);
      mManual.classList.toggle("active", !isDisabled && isOverride);
      mOff.classList.toggle("active", isDisabled);
      if (tMuss)
        tMuss.classList.toggle("active", this._st(e.mussHeute) === "on");

      // Focus guard via :focus, NOT document.activeElement: the panel is
      // mounted inside HA's shadow roots, so activeElement is retargeted
      // to the outer <home-assistant> host and would never equal the input
      // — live updates would clobber the user's typing/drag.
      if (socInput && !socInput.matches(":focus")) {
        const v = this._st(e.socThreshold);
        if (v != null && !isNaN(parseFloat(v))) {
          socInput.value = String(Math.round(parseFloat(v)));
          if (socVal) socVal.textContent = `${socInput.value} %`;
        }
      }
      if (priceInput && !priceInput.matches(":focus")) {
        const v = this._st(e.maxPrice);
        if (v != null && !isNaN(parseFloat(v))) priceInput.value = String(parseFloat(v));
      }
      if (pvInput && !pvInput.matches(":focus")) {
        const v = this._st(e.pvThreshold);
        if (v != null && !isNaN(parseFloat(v))) pvInput.value = String(Math.round(parseFloat(v)));
      }
      if (deadlineInput && !deadlineInput.matches(":focus")) {
        const v = this._st(e.deadline); // "HH:MM:SS" or unknown
        if (v && /^\d{2}:\d{2}/.test(v)) deadlineInput.value = v.slice(0, 5);
      }
    };

    return card;
  }

  _update() {
    for (const key of Object.keys(this._refs)) {
      try {
        this._refs[key]();
      } catch (err) {
        // Keep rendering the other cards, but don't hide bugs entirely.
        console.debug("AURUM panel: updater failed for", key, err);
      }
    }
  }
}

const CSS = `
.aurum-root { padding: 16px; max-width: 1100px; margin: 0 auto;
  color: var(--primary-text-color); box-sizing: border-box; }
.aurum-header { margin-bottom: 16px; }
.aurum-title { font-size: 1.6rem; font-weight: 600; }
.aurum-sub { color: var(--secondary-text-color); font-size: .9rem; }
.aurum-advisor { display: flex; align-items: center; gap: 14px;
  background: var(--card-background-color, #1c1c1c); border-radius: 14px;
  padding: 12px 16px; margin-bottom: 14px;
  border: 1px solid var(--divider-color, transparent);
  border-left: 4px solid var(--secondary-text-color, #888);
  box-shadow: var(--ha-card-box-shadow, none); }
.aurum-advisor-icon { font-size: 1.7rem; }
.aurum-advisor-head { font-weight: 600; font-size: 1.05rem; }
.aurum-advisor-sub { color: var(--secondary-text-color); font-size: .82rem; margin-top: 2px; }
.aurum-overview { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }
.aurum-chip { display: flex; align-items: center; gap: 10px;
  background: var(--card-background-color, #1c1c1c); border-radius: 14px;
  padding: 10px 14px; box-shadow: var(--ha-card-box-shadow, none);
  border: 1px solid var(--divider-color, transparent); min-width: 110px; }
.aurum-chip-icon { font-size: 1.4rem; }
.aurum-chip-value { font-weight: 600; font-size: 1.05rem; }
.aurum-chip-label { color: var(--secondary-text-color); font-size: .75rem; }
.aurum-section { margin-top: 8px; }
.aurum-section-title { font-size: 1.1rem; font-weight: 600; margin: 4px 0 12px; }
.aurum-empty { color: var(--secondary-text-color); background: var(--card-background-color,#1c1c1c);
  border-radius: 14px; padding: 18px; border: 1px dashed var(--divider-color,#444); }
.aurum-devgrid { display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.aurum-card { background: var(--card-background-color, #1c1c1c);
  border-radius: 16px; padding: 14px 16px;
  border: 1px solid var(--divider-color, transparent);
  box-shadow: var(--ha-card-box-shadow, none); }
.aurum-card-top { display: flex; align-items: center; justify-content: space-between; }
.aurum-card-name { font-weight: 600; font-size: 1.05rem; }
.aurum-badge { color: #fff; border-radius: 999px; padding: 2px 10px;
  font-size: .75rem; text-transform: lowercase; }
.aurum-metrics { color: var(--secondary-text-color); font-size: .85rem; margin-top: 8px; min-height: 1.1em; }
.aurum-reason { color: var(--secondary-text-color); font-size: .78rem; font-style: italic; margin-top: 2px; min-height: 1em; }
.aurum-controls { display: flex; flex-wrap: wrap; align-items: center;
  gap: 8px; margin-top: 12px; }
.aurum-seg { display: inline-flex; border: 1px solid var(--divider-color, #555);
  border-radius: 10px; overflow: hidden; }
.aurum-seg-btn { cursor: pointer; border: none; background: transparent;
  color: var(--secondary-text-color); padding: 6px 12px; font-size: .8rem; }
.aurum-seg-btn + .aurum-seg-btn { border-left: 1px solid var(--divider-color, #555); }
.aurum-seg-btn.active { background: var(--primary-color, #03a9f4); color: #fff; }
.aurum-seg-btn:last-child.active { background: var(--error-color, #db4437); }
.aurum-toggle { cursor: pointer; border: 1px solid var(--divider-color, #555);
  background: transparent; color: var(--primary-text-color);
  border-radius: 10px; padding: 6px 10px; font-size: .8rem; }
.aurum-toggle.active { background: #ffb300; border-color: #ffb300; color: #000; }
.aurum-inputs { margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.aurum-input-row { display: flex; flex-direction: column; gap: 4px; font-size: .8rem;
  color: var(--secondary-text-color); }
.aurum-input-inline { flex-direction: row; align-items: center; justify-content: space-between; }
.aurum-input-head { display: flex; justify-content: space-between; }
.aurum-input-val { color: var(--primary-text-color); }
.aurum-input-row input[type=range] { width: 100%; accent-color: var(--primary-color, #03a9f4); }
.aurum-num { width: 90px; background: var(--secondary-background-color, #2a2a2a);
  color: var(--primary-text-color); border: 1px solid var(--divider-color,#555);
  border-radius: 8px; padding: 4px 8px; }
`;

customElements.define("aurum-panel", AurumPanel);
