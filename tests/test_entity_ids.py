"""Fixed entity ids and the panel's hub lookup (v1.16.1, issue #31).

The dashboard panel read the hub sensors from fixed ids such as
``sensor.aurum_pv_power``, but only the per-device entities and the advisor
set their ``entity_id``. The other hub entities got an id derived from their
name. HA 2026.11 regenerates such an id with the device name when the AURUM
device is renamed (``sensor.aurumsolopt_aurum_pv_power``), and the panel then
showed "–" in every tile.

Now every AURUM entity sets a fixed id, and the panel looks the hub entities
up in the entity registry by unique_id, so ids renamed before the update are
found too.
"""

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "aurum"
PANEL = COMP / "frontend" / "aurum-panel.js"
PLATFORMS = ("sensor", "binary_sensor", "number", "switch", "time")


def _template(node):
    """String constant or f-string as text, with ``{expr}`` placeholders."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant)
            else "{" + ast.unparse(v.value) + "}"
            for v in node.values)
    return None


def _entity_classes():
    """(platform, class, {attr: template}) for every class whose __init__
    sets ``self._attr_unique_id``."""
    out = []
    for platform in PLATFORMS:
        tree = ast.parse((COMP / f"{platform}.py").read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            init = next(
                (n for n in cls.body
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None)
            if init is None:
                continue
            attrs = {}
            for node in ast.walk(init):
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                    continue
                t = node.targets[0]
                if (isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "self"):
                    attrs[t.attr] = _template(node.value)
            if "_attr_unique_id" in attrs:
                out.append((platform, cls.name, attrs))
    return out


ENTITIES = _entity_classes()
HUB_UID = re.compile(r"^\{entry\.entry_id\}_([a-z_]+)$")
DEVICE_UID = re.compile(r"^\{entry\.entry_id\}_\{slug\}")


def _hub_entities():
    """unique_id key -> (platform, class, attrs) for the hub entities."""
    hub = {}
    for platform, name, attrs in ENTITIES:
        m = HUB_UID.match(attrs["_attr_unique_id"] or "")
        if m:
            hub[m.group(1)] = (platform, name, attrs)
    return hub


def _js_object(src, name):
    m = re.search(r"const " + name + r" = \{(.*?)\};", src, re.S)
    assert m, f"{name} not found in aurum-panel.js"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', m.group(1)))


class TestFixedEntityIds:

    def test_entity_classes_found(self):
        # Guard against the AST walk silently finding nothing.
        assert len(ENTITIES) >= 25
        assert len(_hub_entities()) >= 17

    @pytest.mark.parametrize(
        "platform,cls,attrs", ENTITIES, ids=[f"{p}.{c}" for p, c, _ in ENTITIES])
    def test_every_entity_sets_a_fixed_entity_id(self, platform, cls, attrs):
        eid = attrs.get("entity_id")
        assert eid, (
            f"{platform}.py {cls} has a unique_id but no fixed entity_id: "
            "HA derives one from the name, which changes with the device name")
        assert eid.startswith(f"{platform}.aurum_")

    def test_hub_ids_are_the_ids_existing_installs_have(self):
        # New installs get the same id that HA derived from the name before,
        # so docs, dashboards and existing installs keep matching.
        for key, (platform, cls, attrs) in _hub_entities().items():
            name = attrs.get("_attr_name")
            assert name and name.startswith("AURUM "), cls
            legacy = platform + "." + re.sub(
                r"[^a-z0-9]+", "_", name.lower()).strip("_")
            assert attrs["entity_id"] == legacy, (cls, attrs["entity_id"], legacy)


class TestPanelHubMap:

    def test_panel_defaults_and_keys_match_the_backend(self):
        src = PANEL.read_text(encoding="utf-8")
        hub_ids = _js_object(src, "HUB")
        hub_keys = _js_object(src, "HUB_KEYS")
        assert set(hub_ids) == set(hub_keys)
        backend = _hub_entities()
        for role, key in hub_keys.items():
            assert key in backend, f"panel role {role}: no hub unique_id {key!r}"
            assert backend[key][2]["entity_id"] == hub_ids[role], role


class TestHealMap:

    def test_heal_covers_every_per_device_entity(self):
        # _async_heal_entity_ids renames per-device ids back on every start;
        # the panel and devices.py build them from the slug.
        tree = ast.parse((COMP / "__init__.py").read_text(encoding="utf-8"))
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "_async_heal_entity_ids")
        heal = {}
        for node in ast.walk(func):
            if (isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Subscript)
                    and getattr(node.targets[0].value, "id", None) == "expected"):
                heal[_template(node.targets[0].slice)] = _template(node.value)
        checked = 0
        for platform, cls, attrs in ENTITIES:
            uid = attrs["_attr_unique_id"] or ""
            if not DEVICE_UID.match(uid):
                continue
            key = uid.replace("{entry.entry_id}", "{eid}")
            assert heal.get(key) == attrs["entity_id"], (cls, key)
            checked += 1
        assert checked >= 8


# ─── Panel behaviour (needs node; skipped without it) ────────────

HARNESS = r"""
global.HTMLElement = class {};
global.customElements = { define: (n, c) => { global.AurumPanel = c; } };
require(process.argv[2]);
const out = {};
const tick = () => new Promise((r) => setTimeout(r, 0));

// Issue #31: AURUM device renamed to "AurumSolOpt", hub ids regenerated.
const REG = [
  { platform: "aurum", config_entry_id: "E1", unique_id: "E1_pv_power",
    entity_id: "sensor.aurumsolopt_aurum_pv_power" },
  { platform: "aurum", config_entry_id: "E1", unique_id: "E1_advisor",
    entity_id: "sensor.aurumsolopt_aurum_current_decision" },
  { platform: "aurum", config_entry_id: "E1", unique_id: "E1_cheap_grid_active",
    entity_id: "binary_sensor.aurumsolopt_aurum_cheap_grid_active" },
  // Same key on another platform / domain: ignored.
  { platform: "other", config_entry_id: "E2", unique_id: "E2_grid_power",
    entity_id: "sensor.other_grid" },
  { platform: "aurum", config_entry_id: "E1", unique_id: "E1_excess",
    entity_id: "number.not_a_sensor" },
  { platform: "aurum", config_entry_id: "E1", unique_id: "E1_boiler",
    entity_id: "sensor.aurum_boiler", name: null,
    original_name: "AURUM Boiler_Stoeckli_Aurum" },
];

(async () => {
  const p = new AurumPanel();
  let syncs = 0, calls = 0;
  p._sync = () => { syncs++; };
  const entities = { "sensor.aurum_boiler": { device_id: "D1" } };
  const devices = { D1: { name: "AURUM", name_by_user: "AurumSolOpt" } };
  const mk = (ents) => ({
    states: {
      "sensor.aurum_boiler": { state: "off",
        attributes: { friendly_name: "AurumSolOpt AURUM Boiler_Stoeckli_Aurum" } },
    },
    entities: ents, devices,
    callWS: (msg) => { calls++; out.msg = msg; return Promise.resolve(REG); },
  });

  // Before the registry answers: default ids, name from friendly_name.
  const h1 = mk(entities);
  p._hass = h1;
  out.nameFriendly = p._devName("boiler", "sensor.aurum_boiler");

  p.hass = h1;
  await tick();
  out.hub = p._hub;
  out.nameRegistry = p._devName("boiler", "sensor.aurum_boiler");
  p.hass = h1; p.hass = mk(entities);  // same registry: no new read
  await tick();
  out.callsSame = calls;
  p.hass = mk({ ...entities });        // registry changed: read again
  await tick();
  out.callsChanged = calls;

  // Default device name, plain friendly name.
  const q = new AurumPanel();
  q._hass = { states: { "sensor.aurum_pool": { attributes: {
      friendly_name: "AURUM Pool" } } },
    entities: { "sensor.aurum_pool": { device_id: "D2" } },
    devices: { D2: { name: "AURUM", name_by_user: null } } };
  out.nameDefault = q._devName("pool", "sensor.aurum_pool");

  // Registry not readable: defaults stay, and it is not retried per update.
  const r = new AurumPanel();
  let rcalls = 0;
  r._sync = () => {};
  const bad = { states: {}, entities: {},
    callWS: () => { rcalls++; return Promise.reject(new Error("nope")); } };
  const origDebug = console.debug; console.debug = () => {};
  r.hass = bad; await tick(); r.hass = bad; await tick();
  console.debug = origDebug;
  out.failHub = r._hub;
  out.failCalls = rcalls;

  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def panel_run(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    harness = tmp_path_factory.mktemp("panel") / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    res = subprocess.run(
        [node, str(harness), str(PANEL)],
        capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


class TestPanelBehaviour:

    def test_hub_ids_come_from_the_registry(self, panel_run):
        hub = panel_run["hub"]
        assert panel_run["msg"] == {"type": "config/entity_registry/list"}
        assert hub["pv"] == "sensor.aurumsolopt_aurum_pv_power"
        assert hub["advisor"] == "sensor.aurumsolopt_aurum_current_decision"
        assert hub["cheap"] == "binary_sensor.aurumsolopt_aurum_cheap_grid_active"

    def test_foreign_and_wrong_domain_entries_are_ignored(self, panel_run):
        hub = panel_run["hub"]
        assert hub["grid"] == "sensor.aurum_grid_power"
        assert hub["surplus"] == "sensor.aurum_excess_power"

    def test_registry_read_once_per_registry_change(self, panel_run):
        assert panel_run["callsSame"] == 1
        assert panel_run["callsChanged"] == 2

    def test_device_name_without_device_prefix(self, panel_run):
        assert panel_run["nameFriendly"] == "Boiler_Stoeckli_Aurum"
        assert panel_run["nameRegistry"] == "Boiler_Stoeckli_Aurum"
        assert panel_run["nameDefault"] == "Pool"

    def test_unreadable_registry_keeps_defaults(self, panel_run):
        assert panel_run["failHub"]["pv"] == "sensor.aurum_pv_power"
        assert panel_run["failHub"]["advisor"] == "sensor.aurum_current_decision"
        assert panel_run["failCalls"] == 1
