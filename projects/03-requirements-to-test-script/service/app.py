"""Test-script service: the two jobs n8n cannot do well on its own.

  POST /prepare  uploaded files (base64)  ->  Claude content blocks (PDF, DOCX text + pictures, images)
  POST /excel    test-script JSON         ->  formatted .xlsx (also saved to OUTPUT_DIR)
  GET  /health

It only listens inside the Docker network. The only outside service it calls is the Figma API,
and only when a Figma link is given and FIGMA_TOKEN is set.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import document_reader
import excel_builder

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(title="Test-script service", version="1.0.0")


class UploadedFile(BaseModel):
    name: str = "file"
    mimeType: str = ""
    data: str
    role: str = "document"


class PrepareRequest(BaseModel):
    files: list[UploadedFile] = Field(default_factory=list)
    maxImages: int = Field(20, ge=0, le=100)
    figmaUrls: list[str] = Field(default_factory=list)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/prepare")
def prepare(request: PrepareRequest):
    try:
        result = document_reader.prepare([f.model_dump() for f in request.files], request.maxImages, request.figmaUrls)
    except Exception as error:  # noqa: BLE001 - report unreadable files to the caller
        raise HTTPException(status_code=422, detail=f"Could not read the uploaded files: {error}") from error
    return {"blocks": result.blocks, "files": result.files, "warnings": result.warnings, "imagesUsed": result.images_used}


@app.post("/excel")
def excel(payload: dict):
    content = excel_builder.build_workbook(payload)
    name = payload.get("filename") or excel_builder.file_name(payload.get("meta") or {})
    if OUTPUT_DIR.is_dir():
        (OUTPUT_DIR / name).write_bytes(content)
    return Response(content=content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
