"""Small production API bridge for the Voice CapCut tab.

The Studio tab remains a static client and keeps its existing Modal/Supabase
flow.  This module only owns /api/capcut/* for the CapCut tab.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capcut_tts_api import CapCutClient  # noqa: E402


VOICE_CATALOG = ROOT / "Voice.json"
OUTPUT_DIR = Path(os.getenv("CAPCUT_OUTPUT_DIR", "/tmp/hth_voicevip_capcut"))
MAX_TEXT = 5000
app = FastAPI(title="HTH Voice CapCut API")


class CapCutTTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    voice: str = Field(default="BV074_streaming", min_length=1, max_length=200)
    resource_id: str | None = Field(default=None, max_length=100)
    rate: float = Field(default=1.0, ge=0.5, le=2.0)


def _voices() -> list[Any]:
    return CapCutClient().list_voices(catalog_path=VOICE_CATALOG)


def _task_parts(payload: dict[str, Any]) -> tuple[str, str]:
    tasks = (payload.get("data") or {}).get("tasks") or []
    if not tasks:
        raise RuntimeError("CapCut không trả về task")
    task = tasks[0]
    task_id, token = str(task.get("id") or ""), str(task.get("token") or "")
    if not task_id or not token:
        raise RuntimeError("Task CapCut thiếu id/token")
    return task_id, token


def _extract_audio_url(payload: dict[str, Any]) -> str | None:
    tasks = (payload.get("data") or {}).get("tasks") or []
    if not tasks:
        return None
    raw = tasks[0].get("payload", {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    items = raw.get("audio_subtitles") or raw.get("audios") or []
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("speech_url") or item.get("audio_url") or item.get("url")
        if url:
            return str(url)
    return None


def _validate_voice(body: CapCutTTSRequest) -> None:
    voices = _voices()
    selected = next((voice for voice in voices if voice.voice_type == body.voice), None)
    if not selected:
        raise ValueError("Voice không có trong Voice.json")
    if body.resource_id and body.resource_id != selected.resource_id:
        raise ValueError("Resource ID không khớp với voice đã chọn")


def _generate(body: CapCutTTSRequest) -> Path:
    _validate_voice(body)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"capcut_{uuid.uuid4().hex}.mp3"

    # Voice.json also contains Microsoft Neural voices. Those are generated
    # through Edge TTS, while CapCut BV voices use the signed CapCut API.
    if "neural" in body.voice.lower():
        import asyncio
        import edge_tts

        rate_percent = int(round((body.rate - 1.0) * 100))

        async def generate() -> None:
            await edge_tts.Communicate(
                body.text, voice=body.voice, rate=f"{rate_percent:+d}%"
            ).save(str(output))

        asyncio.run(generate())
        return output

    client = CapCutClient()
    created = client.create_tts_task(
        body.text,
        voice=body.voice,
        resource_id=body.resource_id,
        rate=f"{body.rate:.1f}",
    )
    task_id, token = _task_parts(created)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = client.query_tts_task(task_id, token)
        tasks = (result.get("data") or {}).get("tasks") or []
        status = str(tasks[0].get("status") or "").lower() if tasks else ""
        if status in {"success", "succeed", "completed", "done", "finish"}:
            audio_url = _extract_audio_url(result)
            if not audio_url:
                raise RuntimeError("CapCut hoàn tất nhưng không có URL file audio")
            with urllib.request.urlopen(audio_url, timeout=60) as response:
                output.write_bytes(response.read())
            return output
        if status in {"failed", "error", "fail"}:
            raise RuntimeError(f"CapCut task thất bại: {status}")
        time.sleep(2)
    raise RuntimeError("CapCut timeout sau 120 giây")


@app.get("/api/capcut/health")
@app.get("/capcut/health")
def capcut_health() -> dict[str, Any]:
    return {"ok": VOICE_CATALOG.exists(), "mode": "vercel-api", "voice_count": len(_voices())}


@app.get("/api/capcut/voices")
@app.get("/capcut/voices")
def capcut_voices() -> list[dict[str, Any]]:
    try:
        return [voice.__dict__ for voice in _voices()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Không tải được Voice.json: {exc}") from exc


@app.post("/api/capcut/tts")
@app.post("/capcut/tts")
def capcut_tts(body: CapCutTTSRequest) -> FileResponse:
    try:
        output = _generate(body)
        return FileResponse(output, media_type="audio/mpeg", filename=output.name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
