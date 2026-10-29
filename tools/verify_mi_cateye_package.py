"""Offline installation preflight, using an extracted archive and real HA."""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "custom_components/mi_cateye/manifest.json").read_text())["version"]
archive = ROOT / ("outputs/Mi-CatEye-" + version + ".zip")
expected = archive.with_suffix(".zip.sha256").read_text().split()[0]
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
with tempfile.TemporaryDirectory(prefix="mi-cateye-install-", dir=ROOT / "work") as directory:
    destination = Path(directory)
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            path = Path(info.filename)
            assert not path.is_absolute() and ".." not in path.parts
        assert package.testzip() is None
        package.extractall(destination)
        manifests = json.loads(package.read("custom_components/mi_cateye/bin/manifest.json"))
        for item in manifests.values():
            info = package.getinfo("custom_components/mi_cateye/bin/" + item["filename"])
            assert (info.external_attr >> 16) & 0o111
    sys.path.insert(0, str(destination / "custom_components"))
    import homeassistant
    component = destination / "custom_components/mi_cateye"
    for source in component.rglob("*.py"):
        compile(source.read_bytes(), str(source.relative_to(component)), "exec")
    for name in ("config_flow", "camera", "event", "sensor", "binary_sensor", "views", "runtime", "recordings"):
        module = importlib.import_module("mi_cateye." + name)
        assert Path(module.__file__).is_relative_to(component)
    from mi_cateye.helpers import bundled_backend
    for machine in ("x86_64", "aarch64"):
        with patch("platform.system", return_value="Linux"), patch("platform.machine", return_value=machine):
            binary, digest = bundled_backend()
            assert binary.is_relative_to(component)
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
    print("PASS: ZIP integrity, safe paths, executable bits, Python compilation, actual-HA imports, amd64/arm64 selection and SHA256")
