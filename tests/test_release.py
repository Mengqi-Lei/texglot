from pathlib import Path

import pytest

from scripts.prepare_release import check_sources, release_body


def test_release_rejects_leaked_key_and_missing_document(tmp_path):
    (tmp_path / "README.md").write_text(
        "[guide](missing.md)\n" + "sk-" + "x" * 30, encoding="utf-8"
    )
    with pytest.raises(ValueError) as error:
        check_sources(tmp_path)
    assert "Possible private data" in str(error.value)
    assert "Broken local link" in str(error.value)
    assert "x" * 30 not in str(error.value)


def test_release_accepts_local_and_external_links_but_not_traversal(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        '[local](guide.md#guide) [remote](https://example.com) <img src="guide.md">',
        encoding="utf-8",
    )
    check_sources(tmp_path)
    readme.write_text("[outside](../outside.md)", encoding="utf-8")
    with pytest.raises(ValueError, match="Broken local link"):
        check_sources(tmp_path)


def test_release_body_links_point_to_versioned_public_files(tmp_path):
    folder = tmp_path / "docs/releases"
    folder.mkdir(parents=True)
    for suffix in ("", "_CN"):
        (folder / f"v1.0.0{suffix}.md").write_text(
            "[README](../../README.md#quick-start)", encoding="utf-8"
        )
    output = release_body(Path(tmp_path), "1.0.0")
    assert (
        output.count(
            "https://github.com/Mengqi-Lei/texglot/blob/v1.0.0/README.md#quick-start"
        )
        == 2
    )
    assert "../../" not in output


async def test_bundled_license_is_text_not_spa_fallback(tmp_path, monkeypatch):
    import httpx

    from app import main

    monkeypatch.setattr(main, "dist", tmp_path)
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1"
    ) as client:
        missing = await client.get("/THIRD_PARTY_LICENSES.txt")
        assert missing.status_code == 404
        (tmp_path / "THIRD_PARTY_LICENSES.txt").write_text(
            "react-dom\nMIT License", encoding="utf-8", newline="\n"
        )
        response = await client.get("/THIRD_PARTY_LICENSES.txt")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text == "react-dom\nMIT License"
