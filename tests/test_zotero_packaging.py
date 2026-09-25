import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.audit_zotero import ZoteroPackageError, audit_package
from scripts.prepare_release import public_files, zotero_update_manifest


def _write_xpi(
    path: Path, members: dict[str, bytes], *, symlink: str | None = None
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo()
            # Preserve deliberately unsafe names on Windows too: its ZipInfo
            # constructor would otherwise change backslashes to forward slashes.
            info.filename = name
            archive.writestr(info, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")


def _manifest() -> bytes:
    return json.dumps(
        {
            "name": "TeXGlot for Zotero",
            "version": "0.1.0",
            "applications": {"gecko": {"id": "zotero@texglot.org"}},
        }
    ).encode()


def test_audit_accepts_runtime_xpi_and_returns_safe_report(tmp_path):
    package = tmp_path / "texglot-zotero-0.1.0.xpi"
    _write_xpi(
        package,
        {
            "manifest.json": _manifest(),
            "bootstrap.js": b"export const version = '0.1.0';\n",
            "chrome/content/menu.js": b"export function register() {}\n",
        },
    )

    report = audit_package(package)

    assert report["manifest"] == {
        "name": "TeXGlot for Zotero",
        "version": "0.1.0",
        "manifest": "manifest.json",
    }
    assert report["member_count"] == 3
    assert report["path"] == package.name
    assert all("/" not in key or not key.startswith("/") for key in report["members"])


def test_audit_accepts_browser_specific_settings_manifest(tmp_path):
    package = tmp_path / "plugin.xpi"
    manifest = {
        "name": "TeXGlot",
        "version": "0.1.0",
        "browser_specific_settings": {"gecko": {"id": "zotero@texglot.org"}},
    }
    _write_xpi(package, {"addon/manifest.json": json.dumps(manifest).encode()})
    assert audit_package(package)["manifest"]["manifest"] == "addon/manifest.json"


def test_audit_rejects_zotero_manifest_without_update_url(tmp_path):
    package = tmp_path / "plugin.xpi"
    manifest = {
        "name": "TeXGlot",
        "version": "0.1.0",
        "applications": {
            "zotero": {
                "id": "zotero@texglot.org",
                "strict_min_version": "9.0",
                "strict_max_version": "10.*",
            }
        },
    }
    _write_xpi(package, {"manifest.json": json.dumps(manifest).encode()})
    with pytest.raises(ZoteroPackageError, match="update_url"):
        audit_package(package)


@pytest.mark.parametrize(
    "name, content, match",
    [
        ("node_modules/dependency.js", b"x", "development/generated"),
        ("private.txt", b"OPENAI_API_KEY = secret", "credential"),
        ("paper.pdf", b"%PDF-1.7", "non-runtime"),
        ("models/weights.safetensors", b"x", "non-runtime"),
    ],
)
def test_audit_rejects_private_or_non_runtime_members(tmp_path, name, content, match):
    package = tmp_path / "plugin.xpi"
    _write_xpi(package, {"manifest.json": _manifest(), name: content})
    with pytest.raises(ZoteroPackageError, match=match):
        audit_package(package)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.js",
        "/absolute.js",
        "C:/absolute.js",
        "nested\\windows.js",
        "truncated\0.js",
    ],
)
def test_audit_rejects_unsafe_paths(tmp_path, name):
    package = tmp_path / "plugin.xpi"
    _write_xpi(package, {"manifest.json": _manifest(), name: b"x"})
    with pytest.raises(ZoteroPackageError, match="archive member"):
        audit_package(package)


def test_audit_checks_raw_names_after_platform_normalization(tmp_path, monkeypatch):
    package = tmp_path / "plugin.xpi"
    _write_xpi(package, {"manifest.json": _manifest(), "nested\\windows.js": b"x"})

    class WindowsZipInfo(zipfile.ZipInfo):
        def __init__(self, filename="NoName", *args, **kwargs):
            super().__init__(filename, *args, **kwargs)
            self.filename = self.filename.replace("\\", "/")

    monkeypatch.setattr(zipfile, "ZipInfo", WindowsZipInfo)
    with pytest.raises(ZoteroPackageError, match="Windows separator"):
        audit_package(package)


def test_audit_rejects_duplicate_members_and_symlinks(tmp_path):
    duplicate = tmp_path / "duplicate.xpi"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("manifest.json", _manifest())
        archive.writestr("manifest.json", _manifest())
    with pytest.raises(ZoteroPackageError, match="duplicate"):
        audit_package(duplicate)

    symlink = tmp_path / "symlink.xpi"
    _write_xpi(symlink, {"manifest.json": _manifest()}, symlink="link.js")
    with pytest.raises(ZoteroPackageError, match="symbolic link"):
        audit_package(symlink)


def test_public_export_includes_source_but_excludes_plugin_build_tree(tmp_path):
    integration = tmp_path / "integrations/zotero"
    (integration / "src").mkdir(parents=True)
    (integration / "node_modules/pkg").mkdir(parents=True)
    (integration / ".scaffold").mkdir(parents=True)
    (integration / "dist").mkdir(parents=True)
    (integration / "docs").mkdir()
    (integration / "docs/development.md").write_text("Public build guide")
    (integration / "docs/qa-profile.md").write_text("Private profile and paper paths")
    (integration / "src/addon.ts").write_text("export {};", encoding="utf-8")
    (integration / "node_modules/pkg/index.js").write_text(
        "generated", encoding="utf-8"
    )
    (integration / ".scaffold/build.xpi").write_bytes(b"generated")
    (integration / "dist/addon.js").write_text("generated", encoding="utf-8")

    paths = {
        path.relative_to(tmp_path).as_posix()
        for path in public_files(tmp_path, "1.0.0")
    }

    assert "integrations/zotero/src/addon.ts" in paths
    assert "integrations/zotero/docs/development.md" in paths
    assert "integrations/zotero/docs/qa-profile.md" not in paths
    assert not any(
        part in path.split("/")
        for path in paths
        for part in ("node_modules", ".scaffold", "dist")
    )


def test_update_manifest_pins_asset_hash_and_host_compatibility(tmp_path):
    package = tmp_path / "texglot-zotero-1.0.0.xpi"
    application = {
        "id": "zotero@texglot.org",
        "strict_min_version": "9.0",
        "strict_max_version": "9.99.99",
    }
    _write_xpi(
        package,
        {
            "manifest.json": json.dumps(
                {"version": "1.0.0", "applications": {"zotero": application}}
            ).encode()
        },
    )
    update = zotero_update_manifest([package], "1.2.0")["addons"][application["id"]][
        "updates"
    ][0]
    assert update["version"] == "1.0.0"
    assert (
        update["update_link"]
        == "https://github.com/Mengqi-Lei/texglot/releases/download/v1.2.0/texglot-zotero-1.0.0.xpi"
    )
    assert (
        update["update_hash"]
        == "sha256:" + hashlib.sha256(package.read_bytes()).hexdigest()
    )
    assert update["applications"]["zotero"] == {
        k: application[k] for k in ("strict_min_version", "strict_max_version")
    }
    with pytest.raises(ValueError, match="Duplicate"):
        zotero_update_manifest([package, package], "1.2.0")
