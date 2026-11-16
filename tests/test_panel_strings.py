"""
Panel strings and the support link in the AURUM sidebar panel.

The panel has no JS test runner, so these checks read aurum-panel.js as
text: English and German must offer the same keys (a missing German key
silently falls back to English), and the footer link must stay a plain,
safe outbound link.
"""

import re
from pathlib import Path

PANEL = (Path(__file__).resolve().parent.parent / "custom_components"
         / "aurum" / "frontend" / "aurum-panel.js")
SRC = PANEL.read_text(encoding="utf-8")


def _keys(lang):
    m = re.search(r"\n  " + lang + r": \{\n(.*?)\n  \},", SRC, re.S)
    assert m, f"STRINGS.{lang} not found"
    return set(re.findall(r"^\s+(\w+):", m.group(1), re.M)) | set(
        re.findall(r"[,{]\s*(\w+):\s*[\"'`]", m.group(1)))


def test_en_and_de_have_the_same_keys():
    en, de = _keys("en"), _keys("de")
    assert len(en) > 40, "key extraction found too little"
    assert en - de == set(), f"missing in de: {sorted(en - de)}"
    assert de - en == set(), f"missing in en: {sorted(de - en)}"


def test_support_strings_exist():
    for lang in ("en", "de"):
        assert {"supportText", "supportLink"} <= _keys(lang)


def test_support_link_is_a_safe_outbound_link():
    m = re.search(r'const SUPPORT_URL = "([^"]+)";', SRC)
    assert m and m.group(1).startswith("https://www.buymeacoffee.com/")
    footer = re.search(r"_buildFooter\(\) \{(.*?)\n  \}", SRC, re.S)
    assert footer, "_buildFooter not found"
    body = footer.group(1)
    assert 'link.target = "_blank"' in body
    assert 'link.rel = "noopener noreferrer"' in body
    # textContent, not innerHTML: translations can never inject markup.
    assert "innerHTML" not in body


def test_footer_is_built_inside_build():
    # The call must sit in _build(), after the innerHTML reset, on a real
    # (not commented-out) line; a plain substring check passed even when
    # the call was commented out.
    m = re.search(r"\n  _build\(devices\) \{(.*?)\n  \}", SRC, re.S)
    assert m, "_build(devices) not found"
    lines = [ln.strip() for ln in m.group(1).splitlines()]
    reset = lines.index('this.innerHTML = "";')
    calls = [i for i, ln in enumerate(lines)
             if ln == "root.appendChild(this._buildFooter());"]
    assert len(calls) == 1, "footer must be appended exactly once"
    assert calls[0] > reset
