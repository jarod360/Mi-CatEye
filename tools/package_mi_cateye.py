"""Build a private-data-free alpha ZIP from explicitly selected sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PIN = "7c05066c90ab6ad1fccb506d5f0408aa31ebe60f"


def run(args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True, encoding="utf-8")


def objects(text):
    decoder = json.JSONDecoder()
    while text.strip():
        text = text.lstrip()
        obj, end = decoder.raw_decode(text)
        yield obj
        text = text[end:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--go", required=True)
    parser.add_argument("--upstream", required=True, type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    if run(["git", "rev-parse", "HEAD"], upstream).strip() != PIN:
        raise SystemExit("Unexpected upstream revision")
    # A modified upstream implementation must never silently enter a release.
    patch = ROOT / "media_core/captcha-refresh.patch"
    changed = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=upstream)
    if not changed:
        subprocess.check_call(["git", "apply", "--check", str(patch.resolve())], cwd=upstream)
        subprocess.check_call(["git", "apply", str(patch.resolve())], cwd=upstream)
        changed = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=upstream)
    if changed.replace(b"\r\n", b"\n") != patch.read_bytes().replace(b"\r\n", b"\n"):
        raise SystemExit("Upstream changes do not exactly match the reviewed captcha patch")
    overlay = upstream / "cmd" / "doorbellcore"
    overlay.mkdir(parents=True, exist_ok=True)
    for name in ("main.go", "main_test.go", "config_patch_test.go"):
        shutil.copyfile(ROOT / "media_core" / name, overlay / name)
    shutil.copyfile(ROOT / "media_core/captcha_refresh_test.go", upstream / "pkg/xiaomi/cateye_refresh_test.go")
    for local, target in (("camera_cloud.go", "pkg/xiaomi/cateye_camera_cloud.go"),
                          ("camera_cloud_test.go", "pkg/xiaomi/cateye_camera_cloud_test.go"),
                          ("recordings.go", "internal/xiaomi/cateye_recordings.go"),
                          ("recordings_test.go", "internal/xiaomi/cateye_recordings_test.go")):
        shutil.copyfile(ROOT / "media_core" / local, upstream / target)
    run([args.go, "test", "./pkg/xiaomi", "./internal/xiaomi", "./cmd/doorbellcore"], upstream)
    version = json.loads((ROOT / "custom_components/mi_cateye/manifest.json").read_text())["version"]
    (ROOT / "work").mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="mi-cateye-package-" + version + "-", dir=ROOT / "work"))
    component = staging / "custom_components/mi_cateye"
    shutil.copytree(ROOT / "custom_components/mi_cateye", component,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "bin"))
    binary_dir = component / "bin"
    binary_dir.mkdir()
    manifest = {}
    env = {**os.environ, "CGO_ENABLED": "0", "GOOS": "linux"}
    for arch in ("amd64", "arm64"):
        env["GOARCH"] = arch
        filename = "mi-cateye-media-linux-" + arch + "-" + version
        target = binary_dir / filename
        run([args.go, "build", "-trimpath", "-ldflags=-s -w -buildid=", "-o", str(target), "./cmd/doorbellcore"], upstream, env)
        data = target.read_bytes()
        if data[:4] != b"\x7fELF":
            raise SystemExit("Not an ELF executable")
        machine = int.from_bytes(data[18:20], "little")
        if machine != {"amd64": 62, "arm64": 183}[arch]:
            raise SystemExit("Wrong executable architecture")
        manifest[arch] = {"filename": filename, "sha256": hashlib.sha256(data).hexdigest()}
    (binary_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    licenses = component / "licenses"
    licenses.mkdir()
    shutil.copyfile(upstream / "LICENSE", licenses / "GO2RTC-LICENSE.txt")
    shutil.copyfile(ROOT / "media_core/SOURCE.json", licenses / "GO2RTC-SOURCE.json")
    shutil.copyfile(patch, licenses / "captcha-refresh.patch")
    # Include notices from every module actually reachable from this profile.
    deps = list(objects(run([args.go, "list", "-deps", "-json", "./cmd/doorbellcore"], upstream, env)))
    modules = {p["Module"]["Path"]: p["Module"] for p in deps if p.get("Module") and not p["Module"].get("Main")}
    inventory = []
    for module, info in sorted(modules.items()):
        directory = Path(info["Dir"])
        notices = [p for p in directory.rglob("*") if p.is_file() and p.name.lower().startswith(("license", "copying", "notice", "patents"))]
        if not notices:
            raise SystemExit("Missing license: " + module)
        destination = licenses / "go-modules" / (module.replace("/", "_") + "@" + info["Version"])
        for path in notices:
            output = destination / path.relative_to(directory)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
        inventory.append({"module": module, "version": info["Version"]})
    goroot = Path(run([args.go, "env", "GOROOT"], upstream).strip())
    for name in ("LICENSE", "PATENTS"):
        if (goroot / name).is_file():
            shutil.copyfile(goroot / name, licenses / ("GOLANG-" + name + ".txt"))
    (licenses / "GO-MODULES.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    shutil.copyfile(ROOT / "docs/mi-cateye-alpha-install.md", staging / "INSTALL.md")
    outputs = ROOT / "outputs"
    outputs.mkdir(exist_ok=True)
    archive = outputs / ("Mi-CatEye-" + version + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(staging).as_posix()
            if any(x in name.split("/") for x in (".local", ".storage", "__pycache__", ".git")):
                raise SystemExit("Private path in package")
            data = path.read_bytes()
            if path.suffix in {".py", ".js", ".json", ".yaml", ".md", ".html"}:
                for forbidden in (b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN OPENSSH PRIVATE KEY-----"):
                    if forbidden in data:
                        raise SystemExit("Personal configuration in " + name)
            item = zipfile.ZipInfo(name, date_time=(2026, 10, 29, 0, 0, 0))
            item.create_system = 3
            mode = 0o755 if path.parent == binary_dir and path.name != "manifest.json" else 0o644
            item.external_attr = (0o100000 | mode) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(item, data)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for item in manifest.values():
            data = package.read("custom_components/mi_cateye/bin/" + item["filename"])
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"package": archive.name, "bytes": archive.stat().st_size, "sha256": digest,
                      "architectures": list(manifest), "dependency_modules": len(inventory)}, indent=2))


if __name__ == "__main__":
    main()
