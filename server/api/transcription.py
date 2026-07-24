"""
Транскрибация вложений: отправка расшифрованного аудио во внешний Speech Analytics API
с callback_url на этот сервис; результат хранится в attachments.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections import deque
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.middleware import get_current_user
from server.database import get_db
from server.database.Attachments import Attachments
from server.database.RoomUsers import RoomUsers
from server.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Transcription"])

MAX_TRANSCRIBE_BYTES = 40 * 1024 * 1024


def _room_member(db: Session, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        db.query(RoomUsers)
        .filter(RoomUsers.room_id == room_id, RoomUsers.user_id == user_id)
        .first()
        is not None
    )


class TranscriptionStatusResponse(BaseModel):
    status: str = Field(..., description="done | pending | failed | none")
    text: str | None = None
    error: str | None = None


def _transcribe_config_ok() -> bool:
    return bool(settings.TRANSCRIBE_CALLBACK_PUBLIC_URL and settings.TRANSCRIBE_WEBHOOK_SECRET)


def _callback_url(attachment_id: uuid.UUID) -> str:
    base = settings.TRANSCRIBE_CALLBACK_PUBLIC_URL
    secret = settings.TRANSCRIBE_WEBHOOK_SECRET
    return f"{base}/api/v1/webhooks/speech-analytics/{attachment_id}?token={quote(secret, safe='')}"


def _nested_dicts_bfs(root: Any) -> list[dict[str, Any]]:
    """Все вложенные dict в JSON (BFS, без циклов по id)."""
    if not isinstance(root, dict):
        return []
    out: list[dict[str, Any]] = []
    dq: deque[dict[str, Any]] = deque([root])
    seen: set[int] = set()
    while dq:
        cur = dq.popleft()
        i = id(cur)
        if i in seen:
            continue
        seen.add(i)
        out.append(cur)
        for v in cur.values():
            if isinstance(v, dict):
                dq.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        dq.append(item)
    return out


# Только улучшенная расшифровка (GigaAM / AiConclusion); исходную ASR не смешиваем.
_CORRECTED_TRANSCRIPTION_KEYS = (
    "corrected_transcription",
    "correctedTranscription",
    "improved_transcription",
    "improvedTranscription",
    "corrected",  # краткий алиас в некоторых callback
)


def _extract_text_from_webhook_body(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Разбор тела callback от внешнего сервиса.
    В БД пишем только улучшенный текст, если он есть; иначе — сырую transcription (fallback).
    Возвращает (text, error).
    """
    if not isinstance(body, dict):
        return None, "invalid json"

    err = body.get("error")
    if isinstance(err, str) and err.strip():
        if body.get("success") is False:
            return None, err.strip()

    for d in _nested_dicts_bfs(body):
        for key in _CORRECTED_TRANSCRIPTION_KEYS:
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip(), None

    for d in _nested_dicts_bfs(body):
        v = d.get("transcription")
        if isinstance(v, str) and v.strip():
            return v.strip(), None

    for d in _nested_dicts_bfs(body):
        v = d.get("text")
        if isinstance(v, str) and v.strip():
            return v.strip(), None

    for d in _nested_dicts_bfs(body):
        err2 = d.get("error")
        if isinstance(err2, str) and err2.strip():
            return None, err2.strip()

    if isinstance(err, str) and err.strip():
        return None, err.strip()

    return None, None


def _dedupe_repeated_transcription_lines(text: str) -> str:
    """
    Callback иногда кладёт в одно поле одну и ту же фразу несколько раз через перевод строки.
    Если все непустые строки совпадают — оставляем одну.
    """
    t = text.strip()
    if not t:
        return t
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) >= 2 and all(ln == lines[0] for ln in lines):
        return lines[0]
    return t


ALLOWED_SPEECH_AUDIO_EXT = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})

MIME_TO_SPEECH_EXT: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "application/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}


def filename_for_speech_analytics_upload(filename: str, content_type: str) -> str:
    """
    Имя файла для multipart во внешний API: только разрешённые расширения.
    Иначе подставляем расширение по Content-Type (кроме webm — не поддерживается их API).
    """
    name = (filename or "audio").strip() or "audio"
    base, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext == ".opus":
        ext = ".ogg"
    if ext in ALLOWED_SPEECH_AUDIO_EXT:
        out = f"{base}{ext}" if base else f"audio{ext}"
        return out[-200:] if len(out) > 200 else out

    ct = (content_type or "").split(";")[0].strip().lower()
    if "webm" in ct or ext == ".webm":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Формат WebM не поддерживается сервисом распознавания. "
                "Запишите сообщение заново в обновлённом клиенте (приоритет M4A) "
                "или прикрепите .mp3, .m4a, .wav, .ogg, .flac или .aac."
            ),
        )

    mapped = MIME_TO_SPEECH_EXT.get(ct)
    if mapped:
        stem = base or "audio"
        out = f"{stem}{mapped}"
        return out[-200:] if len(out) > 200 else out

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Расширение аудио не подходит для распознавания. "
            "Нужны: .wav, .mp3, .flac, .ogg, .m4a, .aac (или запись в M4A в браузере)."
        ),
    )


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    size = 0
    chunks: list[bytes] = []
    chunk_size = 1024 * 1024
    while True:
        buf = await upload.read(chunk_size)
        if not buf:
            break
        size += len(buf)
        if size > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
        chunks.append(buf)
    return b"".join(chunks)


def _speech_analytics_error_message(url: str, exc: Exception) -> str:
    """Краткое сообщение для логов и HTTP detail (диагностика интеграции)."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        body = (exc.response.text or "")[:600].strip()
        if len(body) > 400:
            body = body[:400] + "…"
        return f"Speech Analytics HTTP {exc.response.status_code} for {url}: {body or '(empty body)'}"
    if isinstance(exc, httpx.RequestError):
        return f"Speech Analytics request failed ({url}): {exc}"
    return f"Speech Analytics upload failed: {exc}"


async def _post_external_upload(*, file_bytes: bytes, filename: str, content_type: str, callback_url: str) -> None:
    url = f"{settings.SPEECH_ANALYTICS_BASE_URL}/external_audio/upload"
    headers: dict[str, str] = {}
    if settings.SPEECH_ANALYTICS_API_KEY:
        headers["Authorization"] = f"Bearer {settings.SPEECH_ANALYTICS_API_KEY}"

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        files = {"file": (filename, file_bytes, content_type or "application/octet-stream")}
        data = {"callback_url": callback_url}
        try:
            r = await client.post(url, files=files, data=data, headers=headers)
        except httpx.RequestError as e:
            logger.warning("Speech Analytics upload network error: %s", e)
            raise

        if r.status_code >= 400:
            snippet = (r.text or "")[:800]
            logger.warning("Speech Analytics upload failed: %s %s", r.status_code, snippet)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise RuntimeError(_speech_analytics_error_message(url, e)) from e


@router.get("/attachments/{attachment_id}/transcription", response_model=TranscriptionStatusResponse)
async def get_attachment_transcription(
    attachment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    uid = uuid.UUID(str(current_user["user_id"]))
    row = db.query(Attachments).filter(Attachments.id == attachment_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not _room_member(db, row.room_id, uid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    st = (row.transcription_status or "").lower()
    if st == "done" and row.transcription_text:
        return TranscriptionStatusResponse(
            status="done",
            text=_dedupe_repeated_transcription_lines(row.transcription_text),
        )
    if st == "pending":
        return TranscriptionStatusResponse(status="pending")
    if st == "failed":
        return TranscriptionStatusResponse(status="failed", error=row.transcription_error or "failed")
    return TranscriptionStatusResponse(status="none")


@router.post("/attachments/{attachment_id}/transcribe", response_model=TranscriptionStatusResponse)
async def start_attachment_transcribe(
    attachment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    file: UploadFile | None = File(None),
):
    if not _transcribe_config_ok():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription is not configured (TRANSCRIBE_CALLBACK_PUBLIC_URL, TRANSCRIBE_WEBHOOK_SECRET)",
        )

    uid = uuid.UUID(str(current_user["user_id"]))
    row = db.query(Attachments).filter(Attachments.id == attachment_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not _room_member(db, row.room_id, uid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if row.variant != "full":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only full attachment can be transcribed")

    st = (row.transcription_status or "").lower()
    if st == "done" and row.transcription_text:
        return TranscriptionStatusResponse(
            status="done",
            text=_dedupe_repeated_transcription_lines(row.transcription_text),
        )
    if st == "pending":
        return TranscriptionStatusResponse(status="pending")

    if file is None or not (file.filename or "").strip():
        if st == "failed":
            return TranscriptionStatusResponse(status="failed", error=row.transcription_error or "failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multipart file is required to start transcription",
        )

    audio_bytes = await _read_upload_limited(file, MAX_TRANSCRIBE_BYTES)
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    row.transcription_status = "pending"
    row.transcription_error = None
    row.transcription_text = None
    db.commit()

    cb = _callback_url(attachment_id)
    fname = filename_for_speech_analytics_upload(
        file.filename or row.original_filename or "audio.bin",
        file.content_type or row.content_type or "application/octet-stream",
    )
    ctype = (file.content_type or row.content_type or "application/octet-stream")[:250]

    ext_url = f"{settings.SPEECH_ANALYTICS_BASE_URL}/external_audio/upload"
    try:
        await _post_external_upload(
            file_bytes=audio_bytes,
            filename=fname,
            content_type=ctype,
            callback_url=cb,
        )
    except Exception as e:
        logger.exception("External transcription upload failed")
        if isinstance(e, RuntimeError):
            detail = str(e)
        elif isinstance(e, httpx.RequestError):
            detail = _speech_analytics_error_message(ext_url, e)
        else:
            detail = f"Speech Analytics upload failed: {e}"
        detail = detail[:1500]
        row.transcription_status = "failed"
        row.transcription_error = detail[:2000]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from e

    return TranscriptionStatusResponse(status="pending")


@router.post("/webhooks/speech-analytics/{attachment_id}")
async def speech_analytics_webhook(
    attachment_id: uuid.UUID,
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    if not settings.TRANSCRIBE_WEBHOOK_SECRET or token != settings.TRANSCRIBE_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")

    row = db.query(Attachments).filter(Attachments.id == attachment_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object expected")

    text, err = _extract_text_from_webhook_body(body)
    if text:
        row.transcription_status = "done"
        row.transcription_text = _dedupe_repeated_transcription_lines(text)
        row.transcription_error = None
    elif err:
        row.transcription_status = "failed"
        row.transcription_error = err[:2000]
        row.transcription_text = None
    else:
        logger.warning(
            "speech webhook: could not parse body for attachment %s: %s",
            attachment_id,
            json.dumps(body, ensure_ascii=False)[:800],
        )
        row.transcription_status = "failed"
        row.transcription_error = "unrecognized callback payload"
        row.transcription_text = None

    db.commit()
    return {"ok": True}
