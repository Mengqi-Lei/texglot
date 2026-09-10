"""Pair stable PDF destinations without changing either document.

LaTeX/hyperref preserves destination IDs (sections, figures, citations, etc.)
across translations. Page-number destinations are deliberately excluded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from .figure_alignment import match_figure_regions

VERSION = 2


def geometry(page):
    box = page.cropbox
    width, height = float(box.width), float(box.height)
    rotation = int(page.get("/Rotate", 0)) % 360
    ratio = width / height if rotation in (90, 270) else height / width
    return box, rotation, ratio


def destination_position(reader, destination):
    page = reader.get_destination_page_number(destination)
    if page is None or not 0 <= page < len(reader.pages):
        return None
    box, rotation, _ = geometry(reader.pages[page])
    top, left = destination.get("/Top"), destination.get("/Left")
    try:
        if rotation == 90:
            fraction = (float(left) - float(box.left)) / float(box.width)
        elif rotation == 180:
            fraction = (float(top) - float(box.bottom)) / float(box.height)
        elif rotation == 270:
            fraction = 1 - (float(left) - float(box.left)) / float(box.width)
        else:
            fraction = (float(box.top) - float(top)) / float(box.height)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return {"page": page + 1, "fraction": max(0.0, min(1.0, fraction))}


def priority(name):
    if name.startswith(("page.", "Hfootnote.", "footnote.")) or name == "Doc-Start":
        return 0
    if name.startswith(
        ("section", "subsection", "subsubsection", "chapter", "part", "appendix")
    ):
        return 12
    if name.startswith(("table", "figure", "subfigure", "lstlisting")):
        return 10
    if name.startswith(("equation", "AMS")):
        return 4
    return 2 if name.startswith("cite.") else 3


def ordered_pairs(candidates):
    """Maximum-weight monotone chain, rejecting floating/reordered landmarks.

    The same chain is used in both directions so scrolling cannot run backwards
    or select a different mapping merely because the user changes the active pane.
    """
    items = sorted(
        candidates,
        key=lambda p: (
            p["original"]["page"] + p["original"]["fraction"],
            -p["weight"],
            p["id"],
        ),
    )
    scores, previous = [], []
    for i, item in enumerate(items):
        x = item["original"]["page"] + item["original"]["fraction"]
        y = item["translated"]["page"] + item["translated"]["fraction"]
        best, predecessor = item["weight"], -1
        for j in range(i):
            prior = items[j]
            px = prior["original"]["page"] + prior["original"]["fraction"]
            py = prior["translated"]["page"] + prior["translated"]["fraction"]
            if px < x - 1e-7 and py < y - 1e-7 and scores[j] + item["weight"] > best:
                best, predecessor = scores[j] + item["weight"], j
        scores.append(best)
        previous.append(predecessor)
    if not items:
        return []
    index = max(range(len(items)), key=lambda i: scores[i])
    chain = []
    while index >= 0:
        item = items[index]
        chain.append({key: item[key] for key in ("id", "original", "translated")})
        index = previous[index]
    return list(reversed(chain))


def build_alignment(original: Path, translated: Path, versions: dict):
    readers = {"original": PdfReader(original), "translated": PdfReader(translated)}
    heights = {
        side: [geometry(page)[2] for page in reader.pages]
        for side, reader in readers.items()
    }
    destinations = {side: reader.named_destinations for side, reader in readers.items()}
    candidates = []
    for name in sorted(
        destinations["original"].keys() & destinations["translated"].keys()
    ):
        weight = priority(name)
        if not weight:
            continue
        positions = {
            side: destination_position(reader, destinations[side][name])
            for side, reader in readers.items()
        }
        if all(positions.values()):
            candidates.append({"id": name, "weight": weight, **positions})
    pairs = ordered_pairs(candidates)
    regions = match_figure_regions(readers, candidates)
    return {
        "version": VERSION,
        "kind": "landmarks" if pairs else "pages",
        "documents": versions,
        "heights": heights,
        "pairs": pairs,
        "regions": regions,
    }


@lru_cache(maxsize=16)
def cached_alignment(
    original: str, translated: str, original_version: str, translated_version: str
):
    return build_alignment(
        Path(original),
        Path(translated),
        {"original": original_version, "translated": translated_version},
    )
