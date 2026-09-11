import hashlib

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import Destination, Fit

from app.alignment import build_alignment, ordered_pairs


def paper(path, sizes, destinations):
    writer = PdfWriter()
    for width, height in sizes:
        writer.add_blank_page(width=width, height=height)
    for name, index, top in destinations:
        writer.add_named_destination_object(
            Destination(
                name, writer.pages[index].indirect_reference, Fit.xyz(left=40, top=top)
            )
        )
    writer.write(path)


def test_content_destinations_survive_different_pagination_and_page_heights(tmp_path):
    original, translated = tmp_path / "a.pdf", tmp_path / "b.pdf"
    paper(
        original,
        [(600, 800)] * 10,
        [("page.9", 8, 800), ("table.4", 9, 720), ("section.7", 9, 400)],
    )
    paper(
        translated,
        [(600, 900)] * 9,
        [("page.9", 8, 900), ("table.4", 8, 780), ("section.7", 8, 450)],
    )
    before = [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in [original, translated]
    ]
    result = build_alignment(original, translated, {"original": "a", "translated": "b"})
    assert result["kind"] == "landmarks"
    assert [p["id"] for p in result["pairs"]] == ["table.4", "section.7"]
    table = result["pairs"][0]
    assert table["original"] == {"page": 10, "fraction": 0.1}
    assert table["translated"]["page"] == 9
    assert table["translated"]["fraction"] == pytest.approx(120 / 900)
    assert result["heights"]["translated"] == [1.5] * 9
    assert before == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in [original, translated]
    ]


def test_prose_landmarks_remain_monotone_when_floats_are_reordered():
    def pair(name, x, y, weight):
        return {
            "id": name,
            "original": {"page": x, "fraction": 0.1},
            "translated": {"page": y, "fraction": 0.1},
            "weight": weight,
        }

    chain = ordered_pairs(
        [
            pair("section.1", 1, 1, 12),
            pair("floating-note", 2, 9, 1),
            pair("table.4", 3, 2, 10),
            pair("section.7", 4, 3, 12),
        ]
    )
    assert [p["id"] for p in chain] == ["section.1", "table.4", "section.7"]


def test_no_destinations_returns_explicit_page_fallback(tmp_path):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    paper(first, [(600, 800)], [])
    paper(second, [(600, 900)], [])
    result = build_alignment(first, second, {"original": "a", "translated": "b"})
    assert result["kind"] == "pages" and result["pairs"] == []


def test_rotated_and_cropped_destination_geometry(tmp_path):
    from pypdf.generic import RectangleObject

    from app.alignment import destination_position

    writer = PdfWriter()
    p = writer.add_blank_page(width=600, height=800)
    p.cropbox = RectangleObject([20, 50, 580, 750])
    p.rotate(90)
    writer.add_named_destination_object(
        Destination("section.1", p.indirect_reference, Fit.xyz(left=160, top=600))
    )
    path = tmp_path / "rotated.pdf"
    writer.write(path)
    reader = PdfReader(path)
    assert destination_position(reader, reader.named_destinations["section.1"]) == {
        "page": 1,
        "fraction": 0.25,
    }


def illustrated_paper(
    path, translated=False, artwork=b"0 0 m 200 200 l S", repeat=False
):
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
    )

    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=600, height=800)
    page = writer.pages[2 if translated else 1]
    form = DecodedStreamObject()
    form.set_data(artwork)
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(n) for n in (0, 0, 200, 200)]
            ),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(form)}
            )
        }
    )
    y = 300 if translated else 400
    content = DecodedStreamObject()
    command = f"q 1 0 0 1 60 {y} cm /F1 Do Q\n".encode()
    content.set_data(command * (2 if repeat else 1))
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_named_destination_object(
        Destination("figure.1", page.indirect_reference, Fit.xyz(left=60, top=y - 16))
    )
    # The same section occurs after the figure in the source, before it in translation.
    writer.add_named_destination_object(
        Destination(
            "section.1",
            writer.pages[1].indirect_reference,
            Fit.xyz(left=60, top=720 if translated else 160),
        )
    )
    writer.write(path)


def test_identical_figure_region_survives_float_reordering(tmp_path):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    illustrated_paper(first)
    illustrated_paper(second, translated=True)
    result = build_alignment(first, second, {"original": "a", "translated": "b"})
    assert [p["id"] for p in result["pairs"]] == ["section.1"]
    (region,) = result["regions"]
    assert region["id"] == "figure.1"
    assert region["original"]["page"] == 2
    assert region["original"]["start"] == pytest.approx(0.25)
    assert region["original"]["end"] == pytest.approx(0.545)
    assert region["translated"]["page"] == 3
    assert region["translated"]["start"] == pytest.approx(0.375)
    assert region["translated"]["end"] == pytest.approx(0.67)


@pytest.mark.parametrize("changed,repeat", [(True, False), (False, True)])
def test_changed_or_ambiguous_artwork_does_not_claim_a_figure_match(
    tmp_path, changed, repeat
):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    illustrated_paper(first)
    illustrated_paper(
        second,
        translated=True,
        artwork=b"0 200 m 200 0 l S" if changed else b"0 0 m 200 200 l S",
        repeat=repeat,
    )
    result = build_alignment(first, second, {"original": "a", "translated": "b"})
    assert result["regions"] == []


def test_oversized_image_keeps_other_figures_and_section_alignment(
    tmp_path, monkeypatch
):
    """Exercise a real decoder limit without allocating a large bitmap in the test."""
    from pypdf import apply_configuration
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject

    from app.reader import ReaderStore

    folder = tmp_path / "illustrated"
    folder.mkdir()
    for side in ("original", "translated"):
        path = folder / f"{side}.pdf"
        illustrated_paper(path, translated=side == "translated")
        writer = PdfWriter(clone_from=path)
        page = writer.pages[2 if side == "translated" else 1]
        bitmap = DecodedStreamObject()
        bitmap.set_data(b"\x00" * 12000)
        bitmap.update(
            {
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(100),
                NameObject("/Height"): NumberObject(120),
                NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            }
        )
        page["/Resources"]["/XObject"][NameObject("/Large")] = writer._add_object(
            bitmap.flate_encode()
        )
        content = DecodedStreamObject()
        content.set_data(
            page.get_contents().get_data() + b"q 100 0 0 120 40 40 cm /Large Do Q"
        )
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(path)
    job = {
        "id": folder.name,
        "artifacts": {
            "original": "original.pdf",
            "translated": "translated.pdf",
        },
    }
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.pdf")
    }
    with apply_configuration(zlib_maximum_output_length=1024):
        state = ReaderStore(tmp_path).get(job)
    assert state["documents"]["translated"]["pages"] == 4
    assert [p["id"] for p in state["alignment"]["pairs"]] == ["section.1"]
    assert [p["id"] for p in state["alignment"]["regions"]] == ["figure.1"]
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.pdf")
    }


def test_graphic_fingerprint_does_not_decode_large_images(monkeypatch):
    from pypdf.errors import LimitReachedError
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject

    from app.figure_alignment import graphic_signature

    image = DecodedStreamObject()
    image.set_data(b"pixels" * 1000)
    image = image.flate_encode()
    image[NameObject("/Subtype")] = NameObject("/Image")
    image[NameObject("/Width")] = NumberObject(100)

    def no_decode():
        raise LimitReachedError("Bitmap decoding must not run for matching")

    monkeypatch.setattr(image, "get_data", no_decode)
    first = graphic_signature(image)
    assert first == graphic_signature(image)
    image[NameObject("/Width")] = NumberObject(200)
    assert first != graphic_signature(image)


def test_encoded_image_metadata_is_order_independent_and_leaves_source_unchanged():
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject

    from app.figure_alignment import graphic_signature

    data = DecodedStreamObject()
    data.set_data(b"pixels")
    first, second = data.flate_encode(), data.flate_encode()
    fields = [
        (NameObject("/Width"), NumberObject(100)),
        (NameObject("/Height"), NumberObject(200)),
    ]
    first.update(fields)
    second.update(reversed(fields))
    first[NameObject("/Length")] = NumberObject(17)
    before = dict(first)
    assert graphic_signature(first) == graphic_signature(second)
    assert dict(first) == before


def test_image_resource_references_are_not_compared_across_documents():
    from pypdf.generic import EncodedStreamObject, IndirectObject, NameObject

    from app.figure_alignment import graphic_signature

    image = EncodedStreamObject()
    image[NameObject("/ColorSpace")] = IndirectObject(1, 0, PdfWriter())
    with pytest.raises(NotImplementedError):
        graphic_signature(image)
