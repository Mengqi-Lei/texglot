"""Private reader state. Annotation geometry never touches PDF or source artifacts."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .alignment import cached_alignment
from .config import atomic_json

Document = Literal["original", "translated"]
Color = Literal["yellow", "green", "blue", "pink", "purple"]


class Rect(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1.00001 or self.y + self.height > 1.00001:
            raise ValueError("批注位置超出页面")
        return self


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    rects: list[Rect] = Field(min_length=1, max_length=300)


class AnnotationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")
    document: Document
    document_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["highlight", "underline", "note"]
    color: Color = "yellow"
    anchors: list[Anchor] = Field(min_length=1, max_length=20)
    quote: str = Field(default="", max_length=12000)
    comment: str = Field(default="", max_length=8000)


class AnnotationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    color: Color | None = None
    comment: str | None = Field(default=None, max_length=8000)
    deleted: bool | None = None


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    page: int = Field(ge=1)
    fraction: float = Field(ge=0, le=1)
    document_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    viewport: float | None = Field(default=None, ge=0, le=1)


class ReadingState(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    positions: dict[Document, Position]
    active: Document = "translated"
    mode: Literal["original", "translated", "split"] = "split"
    zoom: float = Field(default=1, ge=0.5, le=2.5)
    sync: bool = True
    left: Document = "original"


@lru_cache(maxsize=64)
def _document_info(path: str, size: int, mtime: int, ctime: int):
    source = Path(path)
    with source.open("rb") as file:
        version = hashlib.file_digest(file, "sha256").hexdigest()
    pages = len(PdfReader(source).pages)
    return {"version": version, "pages": pages}


def document_info(path: Path):
    s = path.stat()
    return dict(_document_info(str(path), s.st_size, s.st_mtime_ns, s.st_ctime_ns))


class ReaderStore:
    def __init__(self, root: Path):
        self.root = root
        # API writes run in a thread pool. Service ownership guarantees one process.
        self.lock = threading.RLock()

    def path(self, job):
        return self.root / job["id"] / "reader.json"

    def load(self, job):
        path = self.path(job)
        if not path.exists():
            return {"annotations": [], "reading": None}
        return json.loads(path.read_text(encoding="utf8"))

    def save(self, job, value):
        if len(json.dumps(value, ensure_ascii=False).encode()) > 25 * 1024 * 1024:
            raise HTTPException(400, "批注数据已达容量上限")
        atomic_json(self.path(job), value)

    def documents(self, job):
        return {
            side: document_info(self.root / job["id"] / job["artifacts"][side])
            for side in ("original", "translated")
            if side in job["artifacts"]
            and (self.root / job["id"] / job["artifacts"][side]).is_file()
        }

    def get(self, job):
        with self.lock:
            state = self.load(job)
            documents = self.documents(job)
            alignment = None
            if all(side in documents for side in ("original", "translated")):
                try:
                    alignment = cached_alignment(
                        str(self.root / job["id"] / job["artifacts"]["original"]),
                        str(self.root / job["id"] / job["artifacts"]["translated"]),
                        documents["original"]["version"],
                        documents["translated"]["version"],
                    )
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                    RecursionError,
                    NotImplementedError,
                    PyPdfError,
                ):
                    # A PDF without usable destinations still supports page-local sync.
                    alignment = None
            return dict(state, documents=documents, alignment=alignment)

    def create(self, job, data: AnnotationInput):
        with self.lock:
            value = self.load(job)
            # Client-generated IDs make a retry after a lost response idempotent.
            for item in value["annotations"]:
                if item["id"] == data.id:
                    if (
                        all(item[key] == val for key, val in data.model_dump().items())
                        and not item["deleted"]
                    ):
                        return item
                    raise HTTPException(409, "批注已存在，请刷新后重试")
            doc = self.documents(job).get(data.document)
            if not doc or doc["version"] != data.document_version:
                raise HTTPException(409, "PDF 已更新，请重新打开阅读器")
            if any(anchor.page > doc["pages"] for anchor in data.anchors):
                raise HTTPException(400, "批注页码无效")
            if len(value["annotations"]) >= 5000:
                raise HTTPException(400, "批注数量已达上限")
            item = dict(
                data.model_dump(),
                revision=1,
                deleted=False,
                created_at=time.time(),
                updated_at=time.time(),
            )
            value["annotations"].append(item)
            self.save(job, value)
            return item

    def patch(self, job, annotation_id: str, data: AnnotationPatch):
        with self.lock:
            value = self.load(job)
            for item in value["annotations"]:
                if item["id"] != annotation_id:
                    continue
                if item["revision"] != data.revision:
                    raise HTTPException(409, "批注已在其他窗口修改，请重新加载后再保存")
                changes = data.model_dump(exclude={"revision"}, exclude_none=True)
                if changes:
                    item.update(
                        changes, revision=item["revision"] + 1, updated_at=time.time()
                    )
                    self.save(job, value)
                return item
            raise HTTPException(404, "批注不存在")

    def position(self, job, data: ReadingState):
        with self.lock:
            docs = self.documents(job)
            for side, pos in data.positions.items():
                doc = docs.get(side)
                if (
                    not doc
                    or doc["version"] != pos.document_version
                    or pos.page > doc["pages"]
                ):
                    raise HTTPException(409, "PDF 已更新，请重新打开阅读器")
            state = self.load(job)
            state["reading"] = data.model_dump(exclude_none=True)
            self.save(job, state)
            return {"ok": True}
