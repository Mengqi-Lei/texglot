"""Match unchanged embedded figures even when LaTeX floats cross section boundaries."""

from __future__ import annotations

import hashlib

from pypdf.errors import PdfReadError


def multiply(first, second):
    a, b, c, d, e, f = first
    aa, bb, cc, dd, ee, ff = second
    return (
        a * aa + b * cc,
        a * bb + b * dd,
        c * aa + d * cc,
        c * bb + d * dd,
        e * aa + f * cc + ee,
        e * bb + f * dd + ff,
    )


def graphic_regions(page):
    resources = page.get("/Resources", {}).get("/XObject", {})
    if not resources:
        return []
    stream = page.get_contents()
    if stream is None:
        return []
    box = page.cropbox
    width, height = float(box.width), float(box.height)
    rotation = int(page.get("/Rotate", 0)) % 360
    matrix = (1, 0, 0, 1, 0, 0)
    stack = []
    result = []
    for args, op in stream.operations:
        if op == b"q":
            stack.append(matrix)
        elif op == b"Q":
            matrix = stack.pop() if stack else (1, 0, 0, 1, 0, 0)
        elif op == b"cm" and len(args) == 6:
            matrix = multiply(tuple(float(n) for n in args), matrix)
        elif op == b"Do" and args and args[0] in resources:
            obj = resources[args[0]].get_object()
            subtype = obj.get("/Subtype")
            if subtype not in ("/Form", "/Image"):
                continue
            bounds = obj.get("/BBox", (0, 0, 1, 1))
            transform = multiply(
                tuple(float(n) for n in obj.get("/Matrix", (1, 0, 0, 1, 0, 0))), matrix
            )
            a, b, c, d, e, f = transform
            points = [
                (a * x + c * y + e, b * x + d * y + f)
                for x, y in [
                    (float(bounds[0]), float(bounds[1])),
                    (float(bounds[0]), float(bounds[3])),
                    (float(bounds[2]), float(bounds[1])),
                    (float(bounds[2]), float(bounds[3])),
                ]
            ]
            xs, ys = zip(*points)
            if (max(xs) - min(xs)) / width < 0.1 or (max(ys) - min(ys)) / height < 0.04:
                continue
            if rotation == 90:
                values = [(x - float(box.left)) / width for x in xs]
            elif rotation == 180:
                values = [(y - float(box.bottom)) / height for y in ys]
            elif rotation == 270:
                values = [1 - (x - float(box.left)) / width for x in xs]
            else:
                values = [(float(box.top) - y) / height for y in ys]
            top, bottom = max(0, min(values)), min(1, max(values))
            if bottom <= top:
                continue
            # Match stream bytes only alongside the same named figure destination.
            # This avoids confusing repeated logos or unrelated same-sized figures.
            signature = hashlib.sha256(obj.get_data()).hexdigest()
            result.append({"signature": signature, "start": top, "end": bottom})
    return result


def match_figure_regions(readers, candidates):
    cache = {}
    regions = []
    for candidate in candidates:
        if not candidate["id"].startswith(("figure.", "subfigure.")):
            continue
        sides = {}
        for side, reader in readers.items():
            position = candidate[side]
            key = (side, position["page"])
            if key not in cache:
                try:
                    cache[key] = graphic_regions(reader.pages[position["page"] - 1])
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    IndexError,
                    AttributeError,
                    RecursionError,
                    NotImplementedError,
                    PdfReadError,
                ):
                    # Unsupported artwork must not disable the section map.
                    cache[key] = []
            caption = position["fraction"]
            sides[side] = [
                region
                for region in cache[key]
                if min(abs(region["start"] - caption), abs(region["end"] - caption))
                < 0.065
            ]
        matches = [
            (left, right)
            for left in sides["original"]
            for right in sides["translated"]
            if left["signature"] == right["signature"]
        ]
        # Ambiguous repeated artwork is left to the ordinary content map.
        if len(matches) != 1:
            continue
        pair = {"id": candidate["id"]}
        for side, region in zip(("original", "translated"), matches[0]):
            position = candidate[side]
            pair[side] = {
                "page": position["page"],
                "start": min(region["start"], position["fraction"]),
                "end": min(1, max(region["end"], position["fraction"] + 0.025)),
            }
        regions.append(pair)
    return regions
