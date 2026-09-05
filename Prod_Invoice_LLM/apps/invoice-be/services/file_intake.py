"""File intake normalisation — Feature 28 (image → PDF at the boundary).

Every invoice entry point (multipart upload inbound/outbound, Trainer sample,
SendGrid attachment, Google Drive connector/Autopilot, directory watcher) calls
`normalize_upload()` before anything else touches the bytes. A PDF passes
through byte-identical; an accepted image is converted to a single PDF *once*,
here, so that nothing downstream (blob storage, `_run_ocr()`, the extraction
graph, `GET /invoices/{id}/pdf`, `PdfViewerCanvas`, Drive write-back, dedup
hashing) ever learns that images exist.

Design notes that matter and are easy to break:

* **Bytes beat filenames.** `sniff_format()` reads magic bytes only. A PNG
  named `.pdf` is a PNG; a PDF named `.jpg` is a PDF. This subsumes Gap 355's
  two-step (suffix, then `%PDF` header) validation, where the two checks could
  disagree.
* **Conversion is deterministic.** The same input bytes must always produce the
  same output bytes, because `Invoice.file_hash` / `TenantAutopilotLog.content_hash`
  dedup runs on the *converted* bytes (Feature 28 §3, decision D2 — the original
  image is discarded). PDF metadata is pinned to a fixed epoch/producer and the
  trailer `/ID` is pinned too; PyMuPDF would otherwise derive both from the
  wall clock.
* **Page size == pixel size at 72 dpi.** Nothing is rescaled, so Document
  Intelligence's polygons line up 1:1 with the page the viewer draws.
* No feature flag (decision D1). No provider branch (D4). Chat attachments are
  deliberately *not* routed through here (D5) — they keep Feature 27's native
  image path in `agents/extraction_agent.py::document_to_base64_images()`.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Accepted formats — the single source of truth for what the door lets in.
# No router keeps its own `.endswith(".pdf")` any more.
# ─────────────────────────────────────────────────────────────────────────────

ACCEPTED_IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
)
ACCEPTED_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".pdf"}) | ACCEPTED_IMAGE_SUFFIXES

#: Used verbatim in every 400 so the five doors cannot describe different rules.
#: Replaces the retired "Only PDF is allowed."
ACCEPTED_FORMATS_DETAIL = "Only PDF, PNG, JPG, TIFF, WEBP or BMP is allowed."

#: Decompression-bomb ceiling, checked from the image header before any decode
#: or any fitz allocation.
MAX_IMAGE_PIXELS = 50_000_000

#: Canonical suffix per sniffed format. `.jpeg`/`.tif` are accepted as *input*
#: filenames but never produced here.
_PDF_MAGIC = b"%PDF"
_EPOCH_PDF_DATE = "D:19700101000000Z"
_PDF_PRODUCER = "invoice-intake"

# Formats PyMuPDF embeds happily from their original bytes. Anything else is
# re-encoded to PNG frame-by-frame by Pillow first (TIFF especially — it can be
# multi-frame, and fitz has no frame selector).
_PASSTHROUGH_IMAGE_FORMATS: frozenset[str] = frozenset({".png", ".jpg"})


class UnsupportedUploadError(Exception):
    """The bytes are not a PDF and not an accepted image format."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ImageTooLargeError(Exception):
    """The image exceeds MAX_IMAGE_PIXELS (decompression-bomb guard)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class NormalizedUpload:
    """What every entry point gets back from `normalize_upload()`."""

    pdf_bytes: bytes
    pdf_filename: str
    source_format: str  # canonical sniffed suffix of the *original* bytes
    was_converted: bool


def sniff_format(data: bytes) -> str | None:
    """Return the canonical suffix for `data` based on magic bytes, or None.

    Never trusts a client-supplied filename or `content_type`. Returns one of
    `.pdf`, `.png`, `.jpg`, `.tiff`, `.webp`, `.bmp`.
    """
    if not data:
        return None
    if data[:4] == _PDF_MAGIC:
        return ".pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return ".tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return None


def _frames_as_streams(data: bytes, fmt: str) -> list[tuple[bytes, int, int]]:
    """Decode `data` into per-frame (image bytes, width, height) tuples.

    Enforces MAX_IMAGE_PIXELS from the header *before* any full decode, so an
    oversized file is refused without allocating its pixels — and, per the
    verification plan, before fitz is ever called.
    """
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ImageTooLargeError(
                    f"Image is {width}x{height} pixels, above the "
                    f"{MAX_IMAGE_PIXELS} pixel limit."
                )
            n_frames = int(getattr(probe, "n_frames", 1) or 1)

            if n_frames == 1 and fmt in _PASSTHROUGH_IMAGE_FORMATS:
                # Original bytes are embedded as-is (a JPEG stays DCT-encoded,
                # so a phone photo does not balloon into a raw PNG).
                return [(data, width, height)]

            frames: list[tuple[bytes, int, int]] = []
            for index in range(n_frames):
                probe.seek(index)
                frame = probe.convert("RGB")
                if frame.width * frame.height > MAX_IMAGE_PIXELS:
                    raise ImageTooLargeError(
                        f"Image frame {index} is {frame.width}x{frame.height} "
                        f"pixels, above the {MAX_IMAGE_PIXELS} pixel limit."
                    )
                buffer = io.BytesIO()
                # compress_level pinned: Pillow's default is already 6, but an
                # explicit value keeps the output byte-stable across versions.
                frame.save(buffer, format="PNG", compress_level=6, optimize=False)
                frames.append((buffer.getvalue(), frame.width, frame.height))
            return frames
    except (ImageTooLargeError, UnsupportedUploadError):
        raise
    except Image.DecompressionBombError as exc:
        # Pillow refuses images above ~2x its own MAX_IMAGE_PIXELS from inside
        # Image.open(), before our header check can read `probe.size`. Without
        # this branch the broad handler below would report the file as an
        # unsupported *format* when it is really an oversized one -- the caller
        # would be told to convert a perfectly valid PNG.
        raise ImageTooLargeError(
            f"Image exceeds the {MAX_IMAGE_PIXELS} pixel limit."
        ) from exc
    except Exception as exc:  # pragma: no cover - malformed-image path
        raise UnsupportedUploadError(
            f"The file could not be read as an image. {ACCEPTED_FORMATS_DETAIL}"
        ) from exc


def convert_image_to_pdf(data: bytes, fmt: str) -> bytes:
    """Convert image bytes to PDF bytes. Pure function, deterministic.

    One PDF page per image frame (a multi-page TIFF becomes a multi-page PDF).
    Page size equals the frame's pixel size in points (72 dpi), so no rescaling
    happens and OCR coordinates map 1:1 onto the rendered page.
    """
    import fitz

    frames = _frames_as_streams(data, fmt)

    pdf = fitz.open()
    try:
        for stream, width, height in frames:
            page = pdf.new_page(width=width, height=height)
            page.insert_image(fitz.Rect(0, 0, width, height), stream=stream)

        # Pin everything PyMuPDF would otherwise derive from the wall clock,
        # or the same photo uploaded twice would hash differently and dedup
        # would never fire.
        pdf.set_metadata(
            {
                "producer": _PDF_PRODUCER,
                "creator": _PDF_PRODUCER,
                "creationDate": _EPOCH_PDF_DATE,
                "modDate": _EPOCH_PDF_DATE,
                "title": "",
                "author": "",
                "subject": "",
                "keywords": "",
            }
        )
        out = pdf.tobytes(garbage=4, deflate=True)
    finally:
        pdf.close()

    return _pin_pdf_trailer_id(out)


def _pin_pdf_trailer_id(pdf_bytes: bytes) -> bytes:
    """Rewrite the trailer `/ID` to a fixed value.

    PyMuPDF seeds the document ID from the current time, which alone would make
    two conversions of the same image differ by 32 bytes and defeat hash dedup.
    Reopening with a pinned ID is cheaper and far less fragile than patching the
    byte stream by hand.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        fixed = "<" + "00" * 16 + ">"
        doc.xref_set_key(-1, "ID", f"[{fixed}{fixed}]")
        # no_new_id=True stops PyMuPDF regenerating the second (changed) half of
        # /ID on write — without it the pinned value is overwritten by a
        # time-seeded one and two conversions of the same image differ.
        return doc.tobytes(garbage=0, deflate=True, no_new_id=True)
    finally:
        doc.close()


def normalize_upload(filename: str, data: bytes) -> NormalizedUpload:
    """The one call every entry point makes.

    * sniffed PDF  → passthrough, byte-identical to the pre-Feature-28 path.
    * sniffed image→ converted; the filename's suffix is rewritten to `.pdf`.
    * anything else→ `UnsupportedUploadError`.

    A disagreement between the filename and the bytes is always resolved in
    favour of the bytes.
    """
    safe_name = (filename or "").strip() or "invoice.pdf"
    fmt = sniff_format(data)

    if fmt is None:
        raise UnsupportedUploadError(
            f"Invalid file format: {safe_name}. {ACCEPTED_FORMATS_DETAIL}"
        )

    if fmt == ".pdf":
        return NormalizedUpload(
            pdf_bytes=data,
            pdf_filename=safe_name,
            source_format=".pdf",
            was_converted=False,
        )

    pdf_bytes = convert_image_to_pdf(data, fmt)
    stem = os.path.splitext(os.path.basename(safe_name))[0] or "invoice"
    directory = os.path.dirname(safe_name)
    pdf_filename = os.path.join(directory, f"{stem}.pdf") if directory else f"{stem}.pdf"
    logger.info(
        "Feature 28: converted %s upload '%s' to PDF (%d bytes)",
        fmt, safe_name, len(pdf_bytes),
    )
    return NormalizedUpload(
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_filename,
        source_format=fmt,
        was_converted=True,
    )
