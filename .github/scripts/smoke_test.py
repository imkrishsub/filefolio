"""End-to-end smoke test against a running FileFolio server.

Used by the Windows CI job to check what the unit tests cannot: that a server
started the way the README says can take real uploads, OCR a scanned page with
the system Tesseract/Poppler, file documents into category/year folders on
disk, and run the "Make searchable" tool (ocrmypdf + Ghostscript).

Usage: python .github/scripts/smoke_test.py [base_url]
Exits non-zero on the first failed check. Standard library plus Pillow only.
"""

import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
ROOT = Path(__file__).resolve().parents[2]


def request(method, path, data=None, headers=None, timeout=300):
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def upload(name, pdf_bytes):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf_bytes + f"\r\n--{boundary}--\r\n".encode()
    status, raw = request("POST", "/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    check(status == 200, f"upload {name} returns 200 (got {status}: {raw[:200]!r})")
    return json.loads(raw)


def check(ok, label):
    print(f"{'PASS' if ok else 'FAIL'}  {label}", flush=True)
    if not ok:
        sys.exit(1)


def text_pdf():
    """A one-page PDF with a real text layer."""
    content = b"BT /F1 14 Tf 72 720 Td (Stadtwerke Musterstadt electricity invoice total due 73.07 EUR) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def scanned_pdf():
    """An image-only PDF, like a scanner produces: text must come from OCR."""
    img = Image.new("L", (1654, 2339), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    for i, line in enumerate(["Finanzamt Musterstadt", "Steuerbescheid 2025", "Erstattung 290,00 EUR"]):
        draw.text((150, 200 + i * 90), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    return buf.getvalue()


def main():
    for _ in range(60):
        try:
            if request("GET", "/", timeout=5)[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        check(False, f"server answers at {BASE}")
    check(True, f"server answers at {BASE}")

    text_doc = upload("invoice.pdf", text_pdf())
    scan_doc = upload("scan_0001.pdf", scanned_pdf())

    status, raw = request("GET", "/documents")
    docs = {d["id"]: d for d in json.loads(raw)}
    check(status == 200 and len(docs) == 2, "both documents listed")

    status, raw = request("GET", "/documents?search=Musterstadt")
    hits = {d["id"] for d in json.loads(raw)} if status == 200 else set()
    check(scan_doc["id"] in hits, "scanned page was OCR'd on upload (found by its text)")
    check(text_doc["id"] in hits, "text layer was extracted on upload")

    uploads = ROOT / "uploads"
    filed = [p for p in uploads.rglob("*.pdf") if ".staging" not in p.parts]
    check(len(filed) == 2, f"two PDFs filed on disk under {uploads}")
    for path in filed:
        rel = path.relative_to(uploads).parts
        check(len(rel) == 3 and rel[1].isdigit(), f"filed as <category>/<year>/<name>: {Path(*rel)}")

    thumbs = list((ROOT / "thumbnails").glob("*.jpg"))
    check(len(thumbs) == 2, "a thumbnail was generated for each upload")

    status, raw = request(
        "POST", "/pdf/ocr", json.dumps({"document_id": scan_doc["id"]}).encode(), {"Content-Type": "application/json"}
    )
    check(status == 200, f"Make searchable (ocrmypdf) returns 200 (got {status}: {raw[:300]!r})")

    status, raw = request("GET", f"/download/{text_doc['id']}")
    check(status == 200 and raw.startswith(b"%PDF"), "download returns the PDF")
    print("All smoke checks passed.")


if __name__ == "__main__":
    main()
