"""Release ZIP for the Marketplace download count.

hacs.json sets ``zip_release``: the Marketplace then downloads ``aurum.zip``
from the release and extracts it straight into ``custom_components/aurum/``
(homeassistant/components/marketplace, ``async_download_zip_file``). A ZIP
with a top-level folder would install as ``custom_components/aurum/aurum/``
and break the integration, so the files have to sit at the root.
"""

import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "aurum"
WORKFLOW = ROOT / ".github" / "workflows" / "release-zip.yml"

spec = importlib.util.spec_from_file_location(
    "build_release_zip", ROOT / "tools" / "build_release_zip.py")
brz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brz)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="needs a git checkout")


def _version():
    return json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))[
        "version"]


def test_hacs_json_names_the_asset_the_workflow_uploads():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "aurum.zip"
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "--out aurum.zip" in wf
    assert 'gh release upload "$TAG" aurum.zip' in wf


def test_zip_has_the_integration_files_at_its_root(tmp_path):
    out = tmp_path / "aurum.zip"
    files = brz.build(out, tag=f"v{_version()}")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert sorted(names) == files
        assert "manifest.json" in names
        assert "__init__.py" in names
        assert "frontend/aurum-panel.js" in names
        assert not any(n.startswith("custom_components/") for n in names)
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["domain"] == "aurum"
        assert manifest["version"] == _version()


def test_zip_extracts_to_the_same_tree_as_the_source(tmp_path):
    out = tmp_path / "aurum.zip"
    files = brz.build(out)
    target = tmp_path / "custom_components" / "aurum"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(target)
    for rel in files:
        assert (target / rel).read_bytes() == (COMP / rel).read_bytes(), rel


def test_tag_must_match_the_manifest_version(tmp_path):
    with pytest.raises(SystemExit, match="does not match"):
        brz.build(tmp_path / "aurum.zip", tag="v0.0.1")
