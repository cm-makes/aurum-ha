"""
Smoke tests for AURUM packaging and config-flow integrity.

These run without a Home Assistant install. They catch the common
"integration won't load" failures that the DeviceManager unit suite
can't see:

- manifest.json malformed or missing required fields
- hacs.json malformed
- a Python module fails to compile (typo, bad import)
- config_flow references a CONF_ name that no longer exists in const.py
- a config-flow step has no matching translation entry
- DOMAIN / VERSION / PLATFORMS drift between manifest.json and const.py
"""

from __future__ import annotations

import ast
import json
import os
import py_compile
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "aurum"
MANIFEST_PATH = COMPONENT_DIR / "manifest.json"
CONST_PATH = COMPONENT_DIR / "const.py"
CONFIG_FLOW_PATH = COMPONENT_DIR / "config_flow.py"
STRINGS_PATH = COMPONENT_DIR / "strings.json"
HACS_PATH = REPO_ROOT / "hacs.json"
TRANSLATIONS_DIR = COMPONENT_DIR / "translations"


# ─── helpers ─────────────────────────────────────────────────────


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _const_names(path: Path) -> set[str]:
    """Return all top-level names assigned in const.py."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _const_value(path: Path, name: str):
    """Read a literal top-level constant from const.py without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise KeyError(name)


def _imported_const_names(path: Path) -> set[str]:
    """Return names imported via ``from .const import ...`` in path."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "const":
            for alias in node.names:
                names.add(alias.name)
    return names


def _config_flow_step_ids(path: Path) -> dict[str, set[str]]:
    """Return {flow_class: {step_ids}} declared in config_flow.py.

    We pick up step_ids by scanning ``step_id="..."`` literals inside each
    flow class's methods. That's looser than parsing async method names
    but matches what HA actually shows the user.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        steps: set[str] = set()
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.keyword)
                and sub.arg == "step_id"
                and isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, str)
            ):
                steps.add(sub.value.value)
        if steps:
            out[node.name] = steps
    return out


# ─── manifest.json ───────────────────────────────────────────────


class TestManifest:
    """Catches the most common 'HA refuses to load the integration' bugs."""

    def test_manifest_is_valid_json(self):
        _load_json(MANIFEST_PATH)

    def test_manifest_has_required_keys(self):
        manifest = _load_json(MANIFEST_PATH)
        required = {
            "domain",
            "name",
            "version",
            "config_flow",
            "documentation",
            "issue_tracker",
            "codeowners",
            "iot_class",
        }
        missing = required - manifest.keys()
        assert not missing, f"manifest.json missing keys: {missing}"

    def test_manifest_domain_matches_const(self):
        manifest = _load_json(MANIFEST_PATH)
        assert manifest["domain"] == _const_value(CONST_PATH, "DOMAIN")

    def test_manifest_version_matches_const(self):
        manifest = _load_json(MANIFEST_PATH)
        assert manifest["version"] == _const_value(CONST_PATH, "VERSION"), (
            "manifest.json version and const.VERSION drifted apart — "
            "bump both together"
        )

    def test_manifest_version_is_semver(self):
        manifest = _load_json(MANIFEST_PATH)
        assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]), (
            f"version {manifest['version']!r} is not MAJOR.MINOR.PATCH"
        )

    def test_manifest_config_flow_enabled(self):
        manifest = _load_json(MANIFEST_PATH)
        assert manifest["config_flow"] is True

    def test_manifest_codeowners_format(self):
        manifest = _load_json(MANIFEST_PATH)
        assert isinstance(manifest["codeowners"], list)
        assert manifest["codeowners"], "codeowners must not be empty"
        for owner in manifest["codeowners"]:
            assert owner.startswith("@"), f"codeowner {owner!r} must start with @"

    def test_manifest_iot_class_is_known(self):
        manifest = _load_json(MANIFEST_PATH)
        # https://developers.home-assistant.io/docs/creating_integration_manifest#iot-class
        valid = {
            "assumed_state",
            "cloud_polling",
            "cloud_push",
            "local_polling",
            "local_push",
            "calculated",
        }
        assert manifest["iot_class"] in valid


# ─── hacs.json ───────────────────────────────────────────────────


class TestHacs:
    def test_hacs_json_is_valid(self):
        data = _load_json(HACS_PATH)
        assert "name" in data, "hacs.json must declare a name"


# ─── module compilation ─────────────────────────────────────────


class TestModulesCompile:
    """If a .py file doesn't compile, HA can't even load the integration."""

    @pytest.mark.parametrize(
        "py_file",
        sorted(p for p in COMPONENT_DIR.rglob("*.py") if "__pycache__" not in p.parts),
        ids=lambda p: str(p.relative_to(REPO_ROOT)).replace(os.sep, "/"),
    )
    def test_compiles(self, py_file: Path):
        py_compile.compile(str(py_file), doraise=True)


# ─── const + config_flow consistency ────────────────────────────


class TestConstIntegrity:
    """Catches: rename a CONF_ in const.py, forget to update config_flow.py."""

    def test_config_flow_imports_resolve_in_const(self):
        imported = _imported_const_names(CONFIG_FLOW_PATH)
        defined = _const_names(CONST_PATH)
        missing = imported - defined
        assert not missing, (
            f"config_flow.py imports names that const.py no longer defines: "
            f"{sorted(missing)}"
        )

    def test_init_imports_resolve_in_const(self):
        init_path = COMPONENT_DIR / "__init__.py"
        imported = _imported_const_names(init_path)
        defined = _const_names(CONST_PATH)
        missing = imported - defined
        assert not missing, (
            f"__init__.py imports names that const.py no longer defines: "
            f"{sorted(missing)}"
        )

    def test_platforms_const_matches_existing_files(self):
        platforms = _const_value(CONST_PATH, "PLATFORMS")
        for platform in platforms:
            module = COMPONENT_DIR / f"{platform}.py"
            assert module.exists(), (
                f"PLATFORMS lists {platform!r} but {module.name} is missing"
            )


# ─── translations cover every config-flow step ──────────────────


class TestTranslations:
    """Missing translations show up to users as raw step keys ('add_device')."""

    def test_strings_json_is_valid(self):
        _load_json(STRINGS_PATH)

    def test_every_config_flow_step_has_a_string(self):
        strings = _load_json(STRINGS_PATH)
        flow_steps = _config_flow_step_ids(CONFIG_FLOW_PATH)

        # Map flow class → strings.json section
        section_for = {
            "AurumConfigFlow": "config",
            "AurumOptionsFlowHandler": "options",
        }

        problems: list[str] = []
        for flow_class, steps in flow_steps.items():
            section = section_for.get(flow_class)
            if section is None:
                continue
            declared = set(strings.get(section, {}).get("step", {}).keys())
            missing = steps - declared
            if missing:
                problems.append(
                    f"{flow_class}: steps {sorted(missing)} have no entry in "
                    f"strings.json[{section!r}][step]"
                )
        assert not problems, "\n".join(problems)

    @pytest.mark.parametrize(
        "lang_file",
        sorted(TRANSLATIONS_DIR.glob("*.json")),
        ids=lambda p: p.name,
    )
    def test_translation_file_is_valid_json(self, lang_file: Path):
        _load_json(lang_file)

    @pytest.mark.parametrize(
        "lang_file",
        sorted(TRANSLATIONS_DIR.glob("*.json")),
        ids=lambda p: p.name,
    )
    def test_translation_covers_every_config_flow_step(self, lang_file: Path):
        translations = _load_json(lang_file)
        flow_steps = _config_flow_step_ids(CONFIG_FLOW_PATH)
        section_for = {
            "AurumConfigFlow": "config",
            "AurumOptionsFlowHandler": "options",
        }
        problems: list[str] = []
        for flow_class, steps in flow_steps.items():
            section = section_for.get(flow_class)
            if section is None:
                continue
            declared = set(translations.get(section, {}).get("step", {}).keys())
            missing = steps - declared
            if missing:
                problems.append(
                    f"{lang_file.name} / {flow_class}: missing {sorted(missing)}"
                )
        assert not problems, "\n".join(problems)
