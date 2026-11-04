"""
Select-selector option translations must be keyed by the option *value*.

HA's frontend looks up
``component.aurum.selector.<translation_key>.options.<value>`` and falls
back to the option's ``label`` when the key is missing. Up to 1.15.1 the
``action`` (options menu) and ``price_mode`` translations were keyed by the
label instead, so every user saw raw keys like ``menu_add_device`` and
``price_mode_solar_only`` in the UI.

The selectors are read straight from config_flow.py's source (AST), so a
new selector or option is covered without touching this test.
"""

import ast
import json
from pathlib import Path

import pytest

from custom_components.aurum import const

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "aurum"
TRANSLATION_FILES = [
    ROOT / "strings.json",
    ROOT / "translations" / "en.json",
    ROOT / "translations" / "de.json",
]


def _value(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return getattr(const, node.id)
    raise AssertionError(f"unsupported option value: {ast.dump(node)}")


def _selectors_from_config_flow():
    """{translation_key: {option values}} for every SelectSelectorConfig."""
    tree = ast.parse((ROOT / "config_flow.py").read_text(encoding="utf-8"))
    found = {}
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call)
                and getattr(call.func, "attr", None) == "SelectSelectorConfig"):
            continue
        kw = {k.arg: k.value for k in call.keywords}
        if "translation_key" not in kw:
            continue
        key = kw["translation_key"].value
        values = found.setdefault(key, set())
        # Options are either an inline list, or a local variable built from
        # SelectOptionDict(...) calls elsewhere in the enclosing function.
        scope = kw["options"]
        if not isinstance(scope, ast.List):
            scope = next(
                f for f in ast.walk(tree)
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(n is call for n in ast.walk(f)))
        for opt in ast.walk(scope):
            if (isinstance(opt, ast.Call)
                    and getattr(opt.func, "attr", None) == "SelectOptionDict"):
                okw = {k.arg: k.value for k in opt.keywords}
                values.add(_value(okw["value"]))
    return found


SELECTORS = _selectors_from_config_flow()


def test_selectors_found():
    assert {"action", "price_mode", "condition_op"} <= set(SELECTORS)


@pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("translation_key", sorted(SELECTORS))
def test_options_keyed_by_value(path, translation_key):
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = set(data["selector"][translation_key]["options"])
    assert keys == SELECTORS[translation_key]
