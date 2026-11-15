"""Turns uploaded requirement files into content blocks for the Claude Messages API.

- PDF   -> a "document" block. Claude reads PDFs natively, including tables and diagrams.
- DOCX  -> the text (headings as Markdown, tables as Markdown tables, in document order)
           plus the pictures embedded in it (screenshots and wireframes inside an FSD).
- Images (PNG, JPEG, GIF, WebP) -> "image" blocks, scaled down to what Claude uses.
- TXT / MD -> a text block.
- Figma links -> the linked frame (or the first frames of the file) exported as PNG through
           the Figma REST API, using the FIGMA_TOKEN environment variable.
Anything else is skipped with a warning, so one odd attachment never breaks a run.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image

MAX_IMAGE_EDGE = 1568        # longest edge Claude uses without scaling down itself
MIN_IMAGE_EDGE = 120         # smaller pictures are logos and icons, not wireframes
MAX_PDF_BYTES = 30 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class Prepared:
    blocks: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    images_used: int = 0


def kind_of(name: str, mime: str) -> str:
    lower = name.lower()
    if lower.endswith(".pdf") or mime == "application/pdf":
        return "pdf"
    if lower.endswith(".docx") or mime == DOCX_TYPE:
        return "docx"
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")) or mime in IMAGE_TYPES:
        return "image"
    if lower.endswith((".txt", ".md", ".markdown")) or mime.startswith("text/"):
        return "text"
    if lower.endswith(".doc"):
        return "legacy-doc"
    return "unknown"


def image_block(raw: bytes) -> dict | None:
    """Scales an image to at most MAX_IMAGE_EDGE and returns a PNG/JPEG image block, or None for icons."""
    with Image.open(io.BytesIO(raw)) as img:
        img.load()
        if max(img.size) < MIN_IMAGE_EDGE:
            return None
        if max(img.size) > MAX_IMAGE_EDGE:
            img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        out = io.BytesIO()
        if img.mode in ("RGBA", "LA", "P"):
            img.convert("RGBA").save(out, "PNG", optimize=True)
            media = "image/png"
        else:
            img.convert("RGB").save(out, "JPEG", quality=85)
            media = "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(out.getvalue()).decode()}}


def _cell_text(text: str) -> str:
    return " ".join(text.split()).replace("|", "/")


def _paragraph_markdown(p: Paragraph) -> str:
    text = p.text.strip()
    if not text:
        return ""
    style = (p.style.name or "").lower() if p.style is not None else ""
    if style.startswith("heading"):
        level = "".join(ch for ch in style if ch.isdigit()) or "1"
        return "#" * min(int(level), 6) + " " + text
    if style == "title":
        return "# " + text
    if "list" in style:
        return "- " + text
    return text


def _table_markdown(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:          # merged cells repeat; keep each once
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(_cell_text(cell.text))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def docx_to_markdown(document: DocxDocument) -> str:
    parts = []
    for block in document.iter_inner_content():
        text = _paragraph_markdown(block) if isinstance(block, Paragraph) else _table_markdown(block)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def docx_images(raw: bytes) -> list[bytes]:
    """Pictures embedded in a .docx, in the order they are stored."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = sorted(n for n in archive.namelist() if n.startswith("word/media/"))
        return [archive.read(n) for n in names if n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))]


FIGMA_API = "https://api.figma.com/v1"
MAX_FIGMA_FRAMES = 6


def parse_figma_url(url: str) -> tuple[str, str | None]:
    """https://www.figma.com/design/<key>/<name>?node-id=12-34  ->  ("<key>", "12:34")"""
    parsed = urllib.parse.urlparse(url)
    match = re.match(r"^/(?:file|design|proto|board)/([A-Za-z0-9]+)", parsed.path)
    if not parsed.netloc.endswith("figma.com") or not match:
        raise ValueError("not a Figma file link")
    node = urllib.parse.parse_qs(parsed.query).get("node-id", [None])[0]
    return match.group(1), node.replace("-", ":") if node else None


def _get(url: str, token: str | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"X-Figma-Token": token} if token else {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def figma_frames(url: str, token: str) -> list[bytes]:
    key, node = parse_figma_url(url)
    if node:
        ids = [node]
    else:  # no frame selected: take the top-level frames of the first page
        tree = json.loads(_get(f"{FIGMA_API}/files/{key}?depth=2", token))
        page = (tree.get("document", {}).get("children") or [{}])[0]
        ids = [c["id"] for c in page.get("children", []) if c.get("type") in ("FRAME", "SECTION", "COMPONENT")][:MAX_FIGMA_FRAMES]
    if not ids:
        return []
    query = urllib.parse.urlencode({"ids": ",".join(ids), "format": "png", "scale": 1})
    rendered = json.loads(_get(f"{FIGMA_API}/images/{key}?{query}", token))
    if rendered.get("err"):
        raise ValueError(rendered["err"])
    return [_get(link) for link in rendered.get("images", {}).values() if link]


def prepare(files: list[dict], max_images: int = 20, figma_urls: list[str] | None = None) -> Prepared:
    """files: [{name, mimeType, data (base64), role: 'document' | 'wireframe'}]"""
    result = Prepared()

    def add_images(raw_images: list[bytes], label: str) -> int:
        added = 0
        for n, raw in enumerate(raw_images, start=1):
            if result.images_used >= max_images:
                result.warnings.append(f"Image limit ({max_images}) reached; skipped the rest of {label}.")
                break
            try:
                block = image_block(raw)
            except Exception:  # noqa: BLE001 - corrupt or unsupported picture
                result.warnings.append(f"Could not read image {n} in {label}.")
                continue
            if block is None:
                continue
            result.blocks.append({"type": "text", "text": f"[Wireframe / screenshot {n} from {label}]"})
            result.blocks.append(block)
            result.images_used += 1
            added += 1
        return added

    for f in files:
        name = f.get("name") or "file"
        role = f.get("role") or "document"
        try:
            raw = base64.b64decode(f.get("data") or "", validate=False)
        except Exception:  # noqa: BLE001
            result.warnings.append(f"{name}: not valid base64, skipped.")
            continue
        kind = kind_of(name, f.get("mimeType") or "")
        info = {"name": name, "role": role, "kind": kind, "bytes": len(raw)}

        if kind == "pdf":
            if len(raw) > MAX_PDF_BYTES:
                result.warnings.append(f"{name}: larger than 30 MB, skipped. Split the PDF.")
                continue
            result.blocks.append({"type": "document", "title": name,
                                  "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(raw).decode()}})
        elif kind == "docx":
            document = docx.Document(io.BytesIO(raw))
            text = docx_to_markdown(document)
            info["characters"] = len(text)
            result.blocks.append({"type": "text", "text": f'<document name="{name}">\n{text}\n</document>'})
            info["images"] = add_images(docx_images(raw), name)
        elif kind == "image":
            info["images"] = add_images([raw], name)
        elif kind == "text":
            text = raw.decode("utf-8", errors="replace")
            info["characters"] = len(text)
            result.blocks.append({"type": "text", "text": f'<document name="{name}">\n{text}\n</document>'})
        elif kind == "legacy-doc":
            result.warnings.append(f"{name}: old .doc format. Save it as .docx or PDF and upload again.")
            continue
        else:
            result.warnings.append(f"{name}: unsupported file type, skipped. Use PDF, DOCX, TXT, MD or an image.")
            continue
        result.files.append(info)

    token = os.environ.get("FIGMA_TOKEN", "")
    for url in figma_urls or []:
        if not token:
            result.warnings.append("A Figma link was given but FIGMA_TOKEN is not set in .env; the link was skipped.")
            break
        try:
            frames = figma_frames(url, token)
        except Exception as error:  # noqa: BLE001 - a bad link should not stop the run
            result.warnings.append(f"Could not export the Figma link {url[:80]}: {error}")
            continue
        added = add_images(frames, "Figma")
        result.files.append({"name": "Figma frame", "role": "wireframe", "kind": "figma", "images": added})
    return result
