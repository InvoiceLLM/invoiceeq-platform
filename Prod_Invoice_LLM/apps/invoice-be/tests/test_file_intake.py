"""Feature 28 — unit tests for `services/file_intake.py`.

These cover the boundary itself: what the door lets in, what it converts, and
the properties the rest of the system silently depends on.

The load-bearing one is `test_conversion_is_byte_for_byte_deterministic`. Dedup
(`Invoice.file_hash`, `TenantAutopilotLog.content_hash`) runs on the *converted*
bytes because decision D2 discards the original image. If conversion ever picks
up a wall-clock value again — PDF `creationDate`, `modDate`, or the trailer
`/ID` PyMuPDF seeds from the current time — then the same photo uploaded twice
hashes differently, dedup never fires, and a free-tier tenant is charged twice
for one invoice. The failure is silent and only visible in billing, so it is
asserted here rather than left to the router tests.

No DB, no network, no app import — every function under test is pure.
"""
import io
import pathlib

import pytest

from services.file_intake import (
    ACCEPTED_FORMATS_DETAIL,
    ACCEPTED_IMAGE_SUFFIXES,
    ACCEPTED_UPLOAD_SUFFIXES,
    MAX_IMAGE_PIXELS,
    ImageTooLargeError,
    NormalizedUpload,
    UnsupportedUploadError,
    convert_image_to_pdf,
    normalize_upload,
    sniff_format,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "image_uploads"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── sniff_format: bytes decide, never the filename ───────────────────────────

@pytest.mark.parametrize(
    "filename,expected",
    [
        ("real_invoice.pdf", ".pdf"),
        ("invoice_photo.png", ".png"),
        ("invoice_photo.jpg", ".jpg"),
        ("invoice_photo.webp", ".webp"),
        ("invoice_two_page.tiff", ".tiff"),
        ("tiny.gif", None),
    ],
)
def test_sniff_format_identifies_each_fixture_from_its_magic_bytes(filename, expected):
    assert sniff_format(_fixture(filename)) == expected


def test_sniff_format_follows_the_bytes_when_the_name_lies():
    """A `.pdf`-named PNG is a PNG and a `.jpg`-named PDF is a PDF.

    This is the case Gap 355's two-step check could not decide: the suffix test
    and the `%PDF` header test disagreed and the router picked whichever ran
    first.
    """
    assert sniff_format(_fixture("png_named_as.pdf")) == ".png"
    assert sniff_format(_fixture("pdf_named_as.jpg")) == ".pdf"


def test_sniff_format_returns_none_for_empty_and_short_input():
    assert sniff_format(b"") is None
    assert sniff_format(b"%P") is None


def test_sniff_format_recognises_both_tiff_byte_orders_and_bmp():
    assert sniff_format(b"II\x2a\x00rest of file") == ".tiff"
    assert sniff_format(b"MM\x00\x2arest of file") == ".tiff"
    assert sniff_format(b"BMsomething") == ".bmp"


# ── the accept list is one shared object ─────────────────────────────────────

def test_accepted_upload_suffixes_is_pdf_plus_the_image_set():
    assert ACCEPTED_UPLOAD_SUFFIXES == frozenset({".pdf"}) | ACCEPTED_IMAGE_SUFFIXES
    assert ".gif" not in ACCEPTED_UPLOAD_SUFFIXES
    assert ".heic" not in ACCEPTED_UPLOAD_SUFFIXES


def test_accepted_formats_detail_names_every_accepted_format():
    for token in ("PDF", "PNG", "JPG", "TIFF", "WEBP", "BMP"):
        assert token in ACCEPTED_FORMATS_DETAIL


# ── normalize_upload ─────────────────────────────────────────────────────────

def test_pdf_passes_through_byte_identical():
    """The whole design rests on this: a PDF's path after Feature 28 is the
    path it took before it."""
    data = _fixture("real_invoice.pdf")
    result = normalize_upload("real_invoice.pdf", data)
    assert isinstance(result, NormalizedUpload)
    assert result.pdf_bytes == data
    assert result.was_converted is False
    assert result.source_format == ".pdf"
    assert result.pdf_filename == "real_invoice.pdf"


def test_pdf_named_as_an_image_still_passes_through_unconverted():
    data = _fixture("pdf_named_as.jpg")
    result = normalize_upload("pdf_named_as.jpg", data)
    assert result.pdf_bytes == data
    assert result.was_converted is False


@pytest.mark.parametrize(
    "filename,source_format",
    [
        ("invoice_photo.png", ".png"),
        ("invoice_photo.jpg", ".jpg"),
        ("invoice_photo.webp", ".webp"),
        ("invoice_two_page.tiff", ".tiff"),
    ],
)
def test_each_accepted_image_becomes_a_pdf(filename, source_format):
    result = normalize_upload(filename, _fixture(filename))
    assert result.was_converted is True
    assert result.source_format == source_format
    assert result.pdf_bytes.startswith(b"%PDF")
    assert result.pdf_filename.endswith(".pdf")


def test_a_png_named_pdf_is_converted_and_keeps_its_pdf_name():
    result = normalize_upload("png_named_as.pdf", _fixture("png_named_as.pdf"))
    assert result.source_format == ".png"
    assert result.was_converted is True
    assert result.pdf_filename == "png_named_as.pdf"
    assert result.pdf_bytes.startswith(b"%PDF")


def test_the_converted_filename_only_has_its_suffix_rewritten():
    result = normalize_upload("IMG_0421.JPG", _fixture("invoice_photo.jpg"))
    assert result.pdf_filename == "IMG_0421.pdf"


def test_a_blank_filename_does_not_produce_a_suffix_only_name():
    result = normalize_upload("", _fixture("invoice_photo.png"))
    assert result.pdf_filename == "invoice.pdf"


def test_gif_is_refused_with_the_shared_detail_string():
    with pytest.raises(UnsupportedUploadError) as exc:
        normalize_upload("tiny.gif", _fixture("tiny.gif"))
    assert ACCEPTED_FORMATS_DETAIL in exc.value.detail


def test_plain_text_and_empty_uploads_are_refused():
    for data in (b"This is just plain text, not a PDF", b""):
        with pytest.raises(UnsupportedUploadError):
            normalize_upload("invoice.pdf", data)


# ── conversion properties the pipeline depends on ────────────────────────────

def test_conversion_is_byte_for_byte_deterministic():
    """The dedup guarantee. See this module's docstring for the consequence."""
    data = _fixture("invoice_photo.jpg")
    assert convert_image_to_pdf(data, ".jpg") == convert_image_to_pdf(data, ".jpg")


def test_determinism_holds_for_every_accepted_image_format():
    for filename, fmt in [
        ("invoice_photo.png", ".png"),
        ("invoice_photo.webp", ".webp"),
        ("invoice_two_page.tiff", ".tiff"),
    ]:
        data = _fixture(filename)
        assert convert_image_to_pdf(data, fmt) == convert_image_to_pdf(data, fmt), filename


def test_determinism_survives_going_through_normalize_upload_twice():
    data = _fixture("invoice_photo.png")
    assert normalize_upload("a.png", data).pdf_bytes == normalize_upload("b.png", data).pdf_bytes


def test_a_two_page_tiff_becomes_a_two_page_pdf():
    import fitz

    doc = fitz.open(stream=convert_image_to_pdf(_fixture("invoice_two_page.tiff"), ".tiff"),
                    filetype="pdf")
    try:
        assert doc.page_count == 2
    finally:
        doc.close()


def test_a_single_frame_image_becomes_a_one_page_pdf():
    import fitz

    doc = fitz.open(stream=convert_image_to_pdf(_fixture("invoice_photo.png"), ".png"),
                    filetype="pdf")
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_page_size_equals_pixel_size_so_ocr_polygons_map_one_to_one():
    """Document Intelligence returns polygons in page points. If the page were
    scaled, `PdfViewerCanvas` would draw every highlight in the wrong place."""
    import fitz
    from PIL import Image

    data = _fixture("invoice_photo.png")
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size

    doc = fitz.open(stream=convert_image_to_pdf(data, ".png"), filetype="pdf")
    try:
        rect = doc[0].rect
        assert (rect.width, rect.height) == (width, height)
    finally:
        doc.close()


# ── the decompression-bomb guard ─────────────────────────────────────────────

def test_oversized_image_raises_before_fitz_is_ever_called(monkeypatch):
    """The cap has to be read from the image *header*. If it were checked after
    decoding, the allocation this guard exists to prevent would already have
    happened."""
    import fitz

    def _explode(*args, **kwargs):
        raise AssertionError("fitz.open() was reached despite the pixel cap")

    monkeypatch.setattr(fitz, "open", _explode)

    with pytest.raises(ImageTooLargeError) as exc:
        convert_image_to_pdf(_fixture("oversized.png"), ".png")
    assert str(MAX_IMAGE_PIXELS) in exc.value.detail


def test_oversized_image_is_refused_through_normalize_upload_too():
    with pytest.raises(ImageTooLargeError):
        normalize_upload("oversized.png", _fixture("oversized.png"))


def test_a_normal_sized_image_is_not_caught_by_the_cap():
    result = normalize_upload("invoice_photo.png", _fixture("invoice_photo.png"))
    assert result.was_converted is True


def test_pillows_own_bomb_error_is_reported_as_too_large_not_unsupported(monkeypatch):
    """Pillow refuses images above ~2x its own limit from inside `Image.open()`,
    before our header check can read `.size`. Mapping that to
    `UnsupportedUploadError` would tell a tenant their valid PNG was the wrong
    *format* and send them off to convert a file that was only ever too big."""
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)

    with pytest.raises(ImageTooLargeError):
        convert_image_to_pdf(_fixture("invoice_photo.png"), ".png")
