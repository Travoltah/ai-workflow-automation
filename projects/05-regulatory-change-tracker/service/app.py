"""Collector service: one endpoint per source check, called by n8n. No AI, no secrets except the database URL.

    POST /collect {"run_id": 3, "source_id": 5}   -> the source's summary (status, new and amended documents, errors)
    GET  /health
"""
import os

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel

from collector import collect

app = FastAPI(title="Regulatory change tracker: collector")
DATABASE_URL = os.environ["DATABASE_URL"]


class CollectRequest(BaseModel):
    run_id: int
    source_id: int | None = None      # None: no source was due; answer "none" so the run still finishes


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/collect")
def collect_source(req: CollectRequest):
    if req.source_id is None:
        return {"source_id": None, "code": None, "status": "none", "items_seen": 0, "new_docs": 0, "amended_docs": 0, "item_errors": [], "error": None}
    with psycopg.connect(DATABASE_URL) as conn:
        return collect(conn, req.source_id, req.run_id)
