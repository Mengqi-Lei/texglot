"""Make CID-keyed CJK output self-contained across PDF readers."""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject


def embed_cjk_mappings(path: Path) -> int:
    writer = PdfWriter(clone_from=path)
    seen = set()
    count = 0
    cmap = None

    def visit(resources):
        nonlocal count, cmap
        if not resources:
            return
        resources = resources.get_object()
        for ref in resources.get("/Font", {}).values():
            font = ref.get_object()
            if id(font) in seen:
                continue
            seen.add(id(font))
            if (
                font.get("/ToUnicode")
                or not font.get("/DescendantFonts")
                or font.get("/Encoding") not in ("/Identity-H", "/Identity-V")
            ):
                continue
            child = font["/DescendantFonts"][0].get_object()
            system = child.get("/CIDSystemInfo", {})
            if system.get("/Registry") == "Adobe" and system.get("/Ordering") == "GB1":
                if cmap is None:
                    stream = DecodedStreamObject()
                    stream.set_data(
                        (
                            Path(__file__).parent / "resources/cmaps/Adobe-GB1-UCS2"
                        ).read_bytes()
                    )
                    cmap = writer._add_object(stream.flate_encode())
                font[NameObject("/ToUnicode")] = cmap
                count += 1
        for ref in resources.get("/XObject", {}).values():
            obj = ref.get_object()
            if id(obj) not in seen:
                seen.add(id(obj))
                visit(obj.get("/Resources"))

    for page in writer.pages:
        visit(page.get("/Resources"))
    if count:
        temporary = path.with_suffix(".mapped.pdf")
        writer.write(temporary)
    writer.close()
    if count:
        temporary.replace(path)
    return count
