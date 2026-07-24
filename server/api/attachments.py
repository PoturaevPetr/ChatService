import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from server.auth.middleware import get_current_user
from server.database import get_db
from server.database.Attachments import Attachments
from server.database.RoomUsers import RoomUsers

router = APIRouter(prefix="/api/v1", tags=["Attachments"])

MAX_FULL_BYTES = 200 * 1024 * 1024
MAX_THUMB_BYTES = 1024 * 1024


def _attachment_content_disposition(original_filename: str) -> str:
    """
    RFC 6266 / RFC 5987: ASCII `filename` + UTF-8 `filename*`, иначе кириллица в HTTP-заголовке ломает ответ.
    """
    raw = (original_filename or "file").strip() or "file"
    ascii_parts: list[str] = []
    for ch in raw:
        o = ord(ch)
        if o < 32 or o == 127 or ch in '<>:"/\\|?*':
            ascii_parts.append("_")
        elif o < 128:
            ascii_parts.append(ch)
        else:
            ascii_parts.append("_")
    ascii_fn = "".join(ascii_parts).strip("._") or "file.bin"
    ascii_fn = ascii_fn[:180]
    ascii_esc = ascii_fn.replace("\\", "\\\\").replace('"', '\\"')
    utf8_star = quote(raw.encode("utf-8"), safe="")
    return f"attachment; filename=\"{ascii_esc}\"; filename*=UTF-8''{utf8_star}"


def _room_member(db: Session, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        db.query(RoomUsers)
        .filter(RoomUsers.room_id == room_id, RoomUsers.user_id == user_id)
        .first()
        is not None
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


@router.post("/rooms/{room_id}/attachments")
async def upload_room_attachments(
    room_id: uuid.UUID,
    file: UploadFile = File(...),
    thumbnail: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Сохранение зашифрованного на клиенте вложения в БД (BYTEA).
    Ключи расшифровки передаются только внутри зашифрованного тела сообщения (WebSocket).
    """
    uid = uuid.UUID(str(current_user["user_id"]))
    if not _room_member(db, room_id, uid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this room")

    full_bytes = await _read_upload_limited(file, MAX_FULL_BYTES)
    if not full_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    full_id = uuid.uuid4()
    row_full = Attachments(
        id=full_id,
        room_id=room_id,
        uploaded_by=uid,
        variant="full",
        parent_attachment_id=None,
        original_filename=(file.filename or "file.bin")[:500],
        content_type=(file.content_type or "application/octet-stream")[:250],
        size_bytes=len(full_bytes),
        ciphertext=full_bytes,
    )
    db.add(row_full)
    db.flush()

    thumb_id = None
    if thumbnail is not None and (thumbnail.filename or "").strip():
        thumb_bytes = await _read_upload_limited(thumbnail, MAX_THUMB_BYTES)
        if thumb_bytes:
            tid = uuid.uuid4()
            row_thumb = Attachments(
                id=tid,
                room_id=room_id,
                uploaded_by=uid,
                variant="thumb",
                parent_attachment_id=full_id,
                original_filename=(thumbnail.filename or "thumb.bin")[:500],
                content_type=(thumbnail.content_type or "application/octet-stream")[:250],
                size_bytes=len(thumb_bytes),
                ciphertext=thumb_bytes,
            )
            db.add(row_thumb)
            thumb_id = str(tid)

    db.commit()
    return {
        "attachment_id": str(full_id),
        "thumbnail_attachment_id": thumb_id,
    }


@router.get("/attachments/{attachment_id}")
async def download_attachment(
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

    body = bytes(row.ciphertext) if row.ciphertext is not None else b""
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _attachment_content_disposition(row.original_filename or "file"),
            "X-Content-Type-Options": "nosniff",
        },
    )
