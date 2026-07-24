from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from server.auth.middleware import get_current_jwt_user
from server.database import get_db
from server.database.MobileAppReleases import MobileAppReleases
from server.settings import settings

router = APIRouter(prefix="/api/v1/mobile", tags=["Mobile updates"])


def _resolve_templates_dir() -> Path:
    # Корень проекта ChatService: server/api/mobile_updates.py -> ../../
    root = Path(__file__).resolve().parents[2]
    rel = (settings.MOBILE_TEMPLATES_DIR_REL or "server/templates").strip().strip("/")
    return (root / rel).resolve()


templates = Jinja2Templates(directory=str(_resolve_templates_dir()))


def _allowed_extensions_for_platform(platform: str) -> set[str]:
    p = platform.strip().lower()
    if p == "android":
        return {".apk", ".aab"}
    if p == "ios":
        return {".ipa"}
    if p == "macos":
        return {".dmg", ".pkg", ".app.zip"}
    if p == "windows":
        return {".exe", ".msi", ".msix"}
    return set()


class VersionCheckRequest(BaseModel):
    platform: str = Field(..., description="android | ios")
    app_version: str = Field(..., description="Текущая версия клиента, например 1.2.3")


class VersionCheckResponse(BaseModel):
    has_update: bool
    is_forced: bool
    latest_version: Optional[str] = None
    min_supported_version: Optional[str] = None
    download_url: Optional[str] = None
    remind_after_hours: int = 24
    title: str = "Доступно обновление"
    message: str = "Установите новую версию приложения."


def _normalize_version(version: str) -> list[int]:
    raw = (version or "").strip()
    if not raw:
        return []
    cleaned = raw.lstrip("vV")
    parts = cleaned.split(".")
    out: list[int] = []
    for p in parts:
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return out


def _is_version_less(a: str, b: str) -> bool:
    av = _normalize_version(a)
    bv = _normalize_version(b)
    max_len = max(len(av), len(bv))
    av = av + [0] * (max_len - len(av))
    bv = bv + [0] * (max_len - len(bv))
    return av < bv


def _sanitize_filename(raw: str) -> str:
    src = (raw or "release.bin").strip() or "release.bin"
    out = []
    for ch in src:
        o = ord(ch)
        if o < 32 or o == 127 or ch in '<>:"/\\|?*':
            out.append("_")
        else:
            out.append(ch)
    s = "".join(out).strip(" .")
    return s[:180] or "release.bin"


def _ensure_storage_dir() -> Path:
    p = Path(settings.MOBILE_RELEASES_STORAGE_DIR).expanduser()
    if not p.is_absolute():
        # Корень проекта ChatService: server/.. -> ChatService/
        root = Path(__file__).resolve().parents[2]
        p = (root / p).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _choose_latest_release(releases: list[MobileAppReleases]) -> Optional[MobileAppReleases]:
    if not releases:
        return None
    return max(
        releases,
        key=lambda r: (_normalize_version(r.version), r.created_at or datetime.min),
    )


def _recompute_latest_for_platform(db: Session, platform: str) -> None:
    rows = (
        db.query(MobileAppReleases)
        .filter(
            MobileAppReleases.platform == platform,
            MobileAppReleases.is_active == True,  # noqa: E712
        )
        .all()
    )
    latest = _choose_latest_release(rows)
    latest_id = latest.id if latest else None
    for row in rows:
        row.is_latest = row.id == latest_id


def _build_download_url(request: Request, release_id: uuid.UUID) -> str:
    if settings.MOBILE_PUBLIC_BASE_URL:
        return f"{settings.MOBILE_PUBLIC_BASE_URL}/api/v1/mobile/releases/{release_id}/download"

    raw = str(request.url_for("mobile_release_download", release_id=str(release_id)))
    parsed = urlparse(raw)
    # Если сервис стоит за reverse-proxy без корректных x-forwarded-*,
    # url_for может собрать http-ссылку. Для публичного домена chat.pirogov.ai
    # принудительно поднимаем до https, чтобы in-app download на Android не падал.
    if parsed.scheme == "http" and parsed.hostname == "chat.pirogov.ai":
        parsed = parsed._replace(scheme="https")
        return urlunparse(parsed)
    return raw


def _serialize_release_row(request: Request, row: MobileAppReleases) -> dict:
    return {
        "id": str(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "platform": row.platform,
        "version": row.version,
        "is_latest": bool(row.is_latest),
        "force_update": bool(row.force_update),
        "min_supported_version": row.min_supported_version or "",
        "size_bytes": row.size_bytes,
        "download_url": _build_download_url(request, row.id),
    }


def _is_json_request(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    requested_with = (request.headers.get("x-requested-with") or "").lower()
    return "application/json" in accept or requested_with == "xmlhttprequest"


@router.get("/admin/releases", response_class=HTMLResponse, name="mobile_updates_admin_page")
async def mobile_updates_admin_page(
    request: Request,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MobileAppReleases)
        .order_by(MobileAppReleases.created_at.desc())
        .limit(40)
        .all()
    )
    rows_for_template = [_serialize_release_row(request, r) for r in rows]
    context = {
        "request": request,
        "rows": rows_for_template,
        "msg": request.query_params.get("msg", ""),
        "default_remind_hours": 24,
    }
    return templates.TemplateResponse(
        name="mobile_updates_admin.html",
        context=context,
    )


@router.get("/admin/releases/list", name="mobile_updates_releases_list")
async def mobile_updates_releases_list(
    request: Request,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MobileAppReleases)
        .order_by(MobileAppReleases.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [_serialize_release_row(request, r) for r in rows]}


@router.get("/admin/releases/script.js", name="mobile_updates_admin_script")
async def mobile_updates_admin_script():
    path = _resolve_templates_dir() / "mobile_updates_admin.js"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    return FileResponse(path=str(path), media_type="application/javascript; charset=utf-8")


@router.post("/admin/releases/upload", name="mobile_updates_upload_release")
async def mobile_updates_upload_release(
    request: Request,
    platform: str = Form(...),
    version: str = Form(...),
    description: str = Form(...),
    min_supported_version: str = Form(...),
    force_update: str = Form(...),
    remind_after_hours: int = Form(24),
    admin_secret: str = Form(...),
    release_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not (admin_secret or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="admin_secret is required")
    if settings.MOBILE_UPDATE_ADMIN_SECRET and admin_secret != settings.MOBILE_UPDATE_ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin secret")

    normalized_platform = platform.strip().lower()
    if normalized_platform not in {"android", "ios", "macos", "windows"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported platform")
    normalized_version = version.strip()
    if not normalized_version:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="version is required")
    normalized_description = (description or "").strip()
    if not normalized_description:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="description is required")
    normalized_min_supported = (min_supported_version or "").strip()
    if not normalized_min_supported:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="min_supported_version is required")
    if force_update.strip().lower() not in {"soft", "force"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="force_update must be soft or force")

    raw = await release_file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if release_file.content_type and (
        release_file.content_type.startswith("audio/")
        or release_file.content_type.startswith("video/")
        or release_file.content_type.startswith("image/")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only executable release files are allowed",
        )

    storage = _ensure_storage_dir()
    safe_name = _sanitize_filename(release_file.filename or "release.bin")
    lower_name = safe_name.lower()
    allowed_ext = _allowed_extensions_for_platform(normalized_platform)
    if not any(lower_name.endswith(ext) for ext in allowed_ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format for {normalized_platform}. Allowed: {', '.join(sorted(allowed_ext))}",
        )
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    final_name = f"{normalized_platform}_{normalized_version}_{stamp}_{safe_name}"
    file_path = (storage / final_name).resolve()
    with open(file_path, "wb") as f:
        f.write(raw)

    force_flag = str(force_update).strip().lower() == "force"
    row = MobileAppReleases(
        platform=normalized_platform,
        version=normalized_version,
        description=normalized_description,
        original_filename=safe_name,
        content_type=(release_file.content_type or "application/octet-stream")[:255],
        size_bytes=len(raw),
        file_path=str(file_path),
        min_supported_version=normalized_min_supported,
        force_update=force_flag,
        remind_after_hours=max(1, int(remind_after_hours or 24)),
        is_latest=False,
        is_active=True,
        created_by=None,
    )
    db.add(row)
    db.flush()
    _recompute_latest_for_platform(db, normalized_platform)
    db.commit()

    if _is_json_request(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Release uploaded",
                "release": _serialize_release_row(request, row),
            }
        )

    return RedirectResponse(
        url="/api/v1/mobile/admin/releases?msg=Release%20uploaded",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/releases/{release_id}/download", name="mobile_release_download")
async def mobile_release_download(
    release_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    row = db.query(MobileAppReleases).filter(MobileAppReleases.id == release_id).first()
    if not row or not row.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    if not row.file_path or not os.path.isfile(row.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release file missing")
    return FileResponse(
        path=row.file_path,
        media_type=row.content_type or "application/octet-stream",
        filename=row.original_filename or "release.bin",
    )


@router.post("/version-check", response_model=VersionCheckResponse)
async def version_check(
    request: Request,
    body: VersionCheckRequest,
    _current_user: Dict = Depends(get_current_jwt_user),
    db: Session = Depends(get_db),
):
    platform = (body.platform or "").strip().lower()
    latest_row = (
        db.query(MobileAppReleases)
        .filter(
            MobileAppReleases.platform == platform,
            MobileAppReleases.is_active == True,  # noqa: E712
            MobileAppReleases.is_latest == True,  # noqa: E712
        )
        .order_by(MobileAppReleases.created_at.desc())
        .first()
    )

    if latest_row:
        latest = (latest_row.version or "").strip()
        min_supported = (latest_row.min_supported_version or "").strip()
        download_url = _build_download_url(request, latest_row.id)
        remind_after_hours = max(1, int(latest_row.remind_after_hours or 24))
        force_flag = bool(latest_row.force_update)
        server_message = (latest_row.description or "").strip()
    else:
        latest = ""
        min_supported = ""
        download_url = None
        remind_after_hours = 24
        force_flag = False
        server_message = ""

    has_update = bool(latest) and _is_version_less(body.app_version, latest)
    is_forced = (bool(min_supported) and _is_version_less(body.app_version, min_supported)) or (
        force_flag and has_update
    )

    if is_forced:
        title = "Требуется обновление"
        message = (
            server_message
            or "Текущая версия больше не поддерживается. Обновите приложение, чтобы продолжить."
        )
    elif has_update:
        title = "Доступно обновление"
        message = server_message or "Доступна новая версия приложения. Рекомендуем обновиться."
    else:
        title = "Версия актуальна"
        message = "У вас установлена актуальная версия."

    return VersionCheckResponse(
        has_update=has_update,
        is_forced=is_forced,
        latest_version=latest or None,
        min_supported_version=min_supported or None,
        download_url=download_url,
        remind_after_hours=remind_after_hours,
        title=title,
        message=message,
    )
