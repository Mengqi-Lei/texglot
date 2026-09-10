import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter

from app.reader import AnnotationInput, AnnotationPatch, ReaderStore, Rect


def pdf(path, pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=600, height=800)
    writer.write(path)


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "reader-test-job"
    folder.mkdir()
    pdf(folder / "original.pdf")
    pdf(folder / "translated.pdf", 4)
    (folder / "translated-source.zip").write_bytes(b"unchanged source archive")
    job = {
        "id": folder.name,
        "artifacts": {
            "original": "original.pdf",
            "translated": "translated.pdf",
            "source": "translated-source.zip",
        },
    }
    store = ReaderStore(tmp_path)
    version = store.documents(job)["translated"]["version"]
    annotation = AnnotationInput(
        id="test-annotation-001",
        document="translated",
        document_version=version,
        kind="highlight",
        color="yellow",
        anchors=[
            {"page": 2, "rects": [{"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.03}]}
        ],
        quote="Important result",
        comment="My note",
    )
    return store, job, annotation


def test_annotations_persist_without_modifying_artifacts(workspace):
    store, job, annotation = workspace
    directory = store.root / job["id"]
    before = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in job["artifacts"].values()
    }
    created = store.create(job, annotation)
    assert created["revision"] == 1
    assert store.create(job, annotation) == created
    changed = store.patch(
        job,
        created["id"],
        AnnotationPatch(revision=1, color="blue", comment="Updated thought"),
    )
    assert changed["revision"] == 2
    reopened = ReaderStore(store.root).get(job)
    assert len(reopened["annotations"]) == 1
    assert reopened["annotations"][0]["comment"] == "Updated thought"
    # Windows uses the containing user's ACL, not POSIX permission bits.
    if os.name != "nt":
        assert (directory / "reader.json").stat().st_mode & 0o777 == 0o600
    assert before == {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in job["artifacts"].values()
    }
    assert all(
        "/Annots" not in page for page in PdfReader(directory / "translated.pdf").pages
    )


def test_concurrent_updates_cannot_silently_overwrite(workspace):
    store, job, annotation = workspace
    store.create(job, annotation)

    def update(comment):
        try:
            store.patch(
                job, annotation.id, AnnotationPatch(revision=1, comment=comment)
            )
            return "saved"
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(update, ["Window A", "Window B"]))
    assert sorted(map(str, results)) == ["409", "saved"]
    assert store.get(job)["annotations"][0]["revision"] == 2


def test_delete_can_be_undone_and_old_versions_remain_available(workspace):
    store, job, annotation = workspace
    store.create(job, annotation)
    removed = store.patch(job, annotation.id, AnnotationPatch(revision=1, deleted=True))
    restored = store.patch(
        job, annotation.id, AnnotationPatch(revision=removed["revision"], deleted=False)
    )
    assert not restored["deleted"]
    pdf(store.root / job["id"] / "translated.pdf", 5)
    state = store.get(job)
    assert (
        state["annotations"][0]["document_version"]
        != state["documents"]["translated"]["version"]
    )
    with pytest.raises(HTTPException) as error:
        store.create(job, annotation.model_copy(update={"id": "stale-annotation-002"}))
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "values", [{"x": 0.9, "width": 0.2}, {"x": float("nan")}, {"height": 0}, {"y": -1}]
)
def test_annotation_coordinates_are_validated(values):
    with pytest.raises(ValidationError):
        Rect(**({"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1} | values))


async def test_reader_api_roundtrip_and_clean_exports(workspace, monkeypatch):
    import app.main as main

    store, job, annotation = workspace

    class Manager:
        def get(self, job_id):
            if job_id == job["id"]:
                return job
            raise KeyError(job_id)

    monkeypatch.setattr(main, "manager", Manager())
    monkeypatch.setattr(main, "reader_store", store)
    monkeypatch.setattr(main, "JOBS", store.root)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        base = f"/api/jobs/{job['id']}"
        original = (
            await client.get(base + "/artifacts/translated?download=true")
        ).content
        state = (await client.get(base + "/reader")).json()
        assert not state["annotations"]
        for index, kind in enumerate(["highlight", "underline", "note"]):
            response = await client.post(
                base + "/annotations",
                json=annotation.model_copy(
                    update={"id": f"annotation-{index:04d}", "kind": kind}
                ).model_dump(),
            )
            assert response.status_code == 200
        # User quotes/comments must never be passed through interface translation.
        response = await client.patch(
            base + "/annotations/annotation-0000",
            json={"revision": 1, "comment": "翻译完成"},
            headers={"Accept-Language": "en"},
        )
        assert response.json()["comment"] == "翻译完成"
        assert (
            await client.get(base + "/artifacts/translated?download=true")
        ).content == original
        reading = {
            "positions": {
                "translated": {
                    "page": 3,
                    "fraction": 0.4,
                    "document_version": annotation.document_version,
                }
            },
            "mode": "split",
            "sync": False,
            "zoom": 1.2,
            "active": "translated",
        }
        assert (
            await client.put(base + "/reader/position", json=reading)
        ).status_code == 200
        assert (await client.get(base + "/reader")).json()["reading"] == reading
        reading["positions"]["translated"]["viewport"] = 0.2
        assert (
            await client.put(base + "/reader/position", json=reading)
        ).status_code == 200
        assert (await client.get(base + "/reader")).json()["reading"] == reading
        reading["positions"]["translated"]["viewport"] = 2
        assert (
            await client.put(base + "/reader/position", json=reading)
        ).status_code == 422
        rejected = await client.get(
            base + "/artifacts/translated?version=" + "0" * 64,
            headers={"Accept-Language": "en"},
        )
        assert (
            rejected.status_code == 409
            and "PDF has changed" in rejected.json()["detail"]
        )
        invalid = annotation.model_copy(update={"id": "invalid-page-0001"}).model_dump()
        invalid["anchors"][0]["page"] = 99
        assert (
            await client.post(base + "/annotations", json=invalid)
        ).status_code == 400
        blocked = await client.post(
            base + "/annotations",
            json=annotation.model_dump(),
            headers={"Origin": "https://untrusted.test"},
        )
        assert blocked.status_code == 403
