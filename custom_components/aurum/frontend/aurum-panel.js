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

class AurumPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._sig = null; // structural signature (device slugs)
    this._refs = {}; // id -> update fn
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
    const sig = JSON.stringify(
      devices.map((d) => [
        d.slug,
        d.name,
        this._exists(d.e.mussHeute),
        this._exists(d.e.socThreshold),
        this._exists(d.e.maxPrice),
        this._exists(d.e.deadline),
      ])
    );
    if (sig !== this._sig) {
      this._sig = sig;
      this._build(devices);
    }
    this._update(devices);
  }

  _build(devices) {
    this._refs = {};
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

    // Overview chips
    root.appendChild(this._buildOverview());

    // Devices
    const devWrap = document.createElement("div");
    devWrap.className = "aurum-section";
    const h = document.createElement("div");
    h.className = "aurum-section-title";
    h.textContent = "Geräte";
    devWrap.appendChild(h);

    if (!devices.length) {
      const empty = document.createElement("div");
      empty.className = "aurum-empty";
      empty.textContent =
        "Noch keine Geräte konfiguriert. Füge in den AURUM-" +
        "Einstellungen ein Gerät hinzu – es erscheint dann hier automatisch.";
      devWrap.appendChild(empty);
    } else {
      const grid = document.createElement("div");
      grid.className = "aurum-devgrid";
      for (const d of devices) grid.appendChild(this._buildDeviceCard(d));
      devWrap.appendChild(grid);
    }
    root.appendChild(devWrap);
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

    add("pv", "🔆", "Solar", () => {
      const v = parseFloat(this._st(HUB.pv));
      return { text: isNaN(v) ? "–" : `${Math.round(v)} W`, color: "#ffb300" };
    });
    add("grid", "🔌", "Netz", () => {
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
    add("soc", "🔋", "Akku", () => {
      const v = parseFloat(this._st(HUB.soc));
      if (isNaN(v) || v < 0) return { text: "–", color: "var(--secondary-text-color,#888)" };
      const color = v >= 60 ? "var(--success-color,#43a047)" : v >= 30 ? "#ffb300" : "var(--error-color,#db4437)";
      return { text: `${Math.round(v)} %`, color };
    });
    add("surplus", "⚡", "Überschuss", () => {
      const v = parseFloat(this._st(HUB.surplus));
      if (isNaN(v)) return { text: "–" };
      const color = v > 500 ? "var(--success-color,#43a047)" : v > 100 ? "#ffb300" : "var(--secondary-text-color,#888)";
      return { text: `${Math.round(v)} W`, color };
    });
    add("budget", "🎯", "Budget", () => {
      const v = parseFloat(this._st(HUB.budget));
      return { text: isNaN(v) ? "∞" : `${Math.round(v)} W` };
    });
    add("house", "🏠", "Haus", () => {
      const v = parseFloat(this._st(HUB.house));
      return { text: isNaN(v) ? "–" : `${Math.round(v)} W` };
    });
    add("forecast", "📈", "Rest heute", () => {
      const v = parseFloat(this._st(HUB.forecast));
      return { text: isNaN(v) ? "–" : `${v.toFixed(1)} kWh` };
    });
    add("cheap", "💶", "Günstig", () => {
      const on = this._st(HUB.cheap) === "on";
      return {
        text: on ? "aktiv" : "–",
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
    const mPV = mkMode("PV", "AURUM steuert automatisch nach PV-Überschuss", () => {
      svc("turn_off", e.override);
      svc("turn_off", e.disable);
    });
    const mManual = mkMode("Manuell", "AURUM pausiert – du steuerst das Gerät selbst", () => {
      svc("turn_on", e.override);
      svc("turn_off", e.disable);
    });
    const mOff = mkMode("Aus", "Gerät bleibt aus (Force-Off)", () => {
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
      tMuss.textContent = "Muss heute";
      tMuss.title = "Deadline aktivieren – Gerät läuft heute auf jeden Fall";
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
      lab.textContent = "SOC-Schwelle";
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
      lab.textContent = "Max. Preis (ct/kWh)";
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

    let deadlineInput = null;
    if (this._exists(e.deadline)) {
      const row = document.createElement("label");
      row.className = "aurum-input-row aurum-input-inline";
      const lab = document.createElement("span");
      lab.textContent = "Deadline";
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
        badge.textContent = "aus";
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

      const rs = this._attr(e.status, "scheduling_reason");
      reason.textContent = rs ? `→ ${rs}` : "";

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
