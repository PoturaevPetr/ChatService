"""LLM access: encrypted credentials for enabled users + admin toggle."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.middleware import get_current_user
from server.database import get_db
from server.database.Devices import Devices
from server.database.Users import Users
from server.services.llm_access_service import (
    build_encrypted_llm_credentials,
    llm_access_meta,
    llm_server_configured,
)
from server.settings import settings

router = APIRouter(prefix="/api/v1/llm", tags=["LLM"])


def _resolve_templates_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    rel = (settings.MOBILE_TEMPLATES_DIR_REL or "server/templates").strip().strip("/")
    return (root / rel).resolve()


templates = Jinja2Templates(directory=str(_resolve_templates_dir()))


class LlmEncryptedKeyBundle(BaseModel):
    encrypted_data: str
    encrypted_aes_key: str
    nonce: str


class LlmAccessResponse(BaseModel):
    enabled: bool
    base_url: Optional[str] = None
    api_key_header: Optional[str] = Field(
        None,
        description="Имя HTTP-заголовка для ключа; пусто — Authorization: Bearer",
    )
    encrypted_api_key: Optional[LlmEncryptedKeyBundle] = None


class LlmAdminUserRow(BaseModel):
    id: uuid.UUID
    username: str
    service_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    is_active: bool
    is_verified: bool
    llm_enabled: bool


class LlmAdminUserDetail(LlmAdminUserRow):
    birth_date: Optional[str] = None
    has_avatar: bool = False
    created_at: Optional[str] = None
    last_login: Optional[str] = None
    last_seen_at: Optional[str] = None


class LlmAdminSetAccessBody(BaseModel):
    admin_secret: str = Field(..., min_length=1)
    llm_enabled: bool


def _user_to_admin_row(user: Users) -> LlmAdminUserRow:
    return LlmAdminUserRow(
        id=user.id,
        username=user.username,
        service_id=user.service_id,
        first_name=user.first_name,
        last_name=user.last_name,
        middle_name=user.middle_name,
        is_active=bool(user.is_active),
        is_verified=bool(user.is_verified),
        llm_enabled=bool(getattr(user, "llm_enabled", False)),
    )


def _user_to_admin_detail(user: Users) -> LlmAdminUserDetail:
    row = _user_to_admin_row(user)
    birth = user.birth_date.isoformat() if user.birth_date else None
    created = user.created_at.isoformat() if user.created_at else None
    last_login = user.last_login.isoformat() if user.last_login else None
    last_seen = user.last_seen_at.isoformat() if user.last_seen_at else None
    return LlmAdminUserDetail(
        **row.model_dump(),
        birth_date=birth,
        has_avatar=bool(user.avatar and str(user.avatar).strip()),
        created_at=created,
        last_login=last_login,
        last_seen_at=last_seen,
    )


def _verify_admin_secret(admin_secret: str) -> None:
    secret = (admin_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="admin_secret is required")
    configured = (settings.LLM_ADMIN_SECRET or "").strip()
    if configured and secret != configured:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin secret")


def _get_active_device(db: Session, user_id: uuid.UUID, device_id: str) -> Devices:
    row = (
        db.query(Devices)
        .filter(
            Devices.user_id == user_id,
            Devices.device_id == device_id,
            Devices.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not registered. Open the app once to register this device.",
        )
    return row


@router.get("/access", response_model=LlmAccessResponse)
async def get_llm_access(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
):
    uid = current_user["user_id"]
    user: Users | None = db.query(Users).filter(Users.id == uid).first()
    if not user or not getattr(user, "llm_enabled", False):
        return LlmAccessResponse(enabled=False)

    if not llm_server_configured():
        return LlmAccessResponse(enabled=False)

    device_id = (x_device_id or "").strip()
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Device-Id header is required",
        )

    device = _get_active_device(db, uid, device_id)
    try:
        encrypted = build_encrypted_llm_credentials(device.identity_key_public)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    meta = llm_access_meta()
    return LlmAccessResponse(
        enabled=True,
        base_url=meta["base_url"],
        api_key_header=meta["api_key_header"],
        encrypted_api_key=LlmEncryptedKeyBundle(**encrypted),
    )


@router.get("/admin", response_class=HTMLResponse, name="llm_admin_page")
async def llm_admin_page(request: Request):
    return templates.TemplateResponse(
        name="llm_admin.html",
        context={
            "request": request,
            "msg": request.query_params.get("msg", ""),
        },
    )


@router.get("/admin/script.js", name="llm_admin_script")
async def llm_admin_script():
    path = _resolve_templates_dir() / "llm_admin.js"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    return FileResponse(path=str(path), media_type="application/javascript; charset=utf-8")


@router.get("/admin/users", name="llm_admin_users_list")
async def llm_admin_users_list(
    admin_secret: str,
    q: str = "",
    db: Session = Depends(get_db),
):
    _verify_admin_secret(admin_secret)
    query = db.query(Users).order_by(Users.username.asc())
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        query = query.filter(
            (Users.username.ilike(like))
            | (Users.service_id.ilike(like))
            | (Users.first_name.ilike(like))
            | (Users.last_name.ilike(like))
        )
    rows = query.limit(200).all()
    items = [_user_to_admin_row(r) for r in rows]
    return {"items": [i.model_dump(mode="json") for i in items]}


@router.get("/admin/users/{user_id}", name="llm_admin_user_detail")
async def llm_admin_user_detail(
    user_id: uuid.UUID,
    admin_secret: str,
    db: Session = Depends(get_db),
):
    _verify_admin_secret(admin_secret)
    user: Users | None = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_to_admin_detail(user).model_dump(mode="json")


@router.patch("/admin/users/{user_id}/access", name="llm_admin_set_access_json")
async def llm_admin_set_access_json(
    user_id: uuid.UUID,
    body: LlmAdminSetAccessBody,
    db: Session = Depends(get_db),
):
    _verify_admin_secret(body.admin_secret)
    user: Users | None = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.llm_enabled = body.llm_enabled
    db.commit()
    db.refresh(user)
    return _user_to_admin_detail(user).model_dump(mode="json")


@router.post("/admin/users/{user_id}/access", name="llm_admin_set_access")
async def llm_admin_set_access(
    user_id: uuid.UUID,
    admin_secret: str = Form(...),
    llm_enabled: str = Form(...),
    db: Session = Depends(get_db),
):
    _verify_admin_secret(admin_secret)
    user: Users | None = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    enabled = llm_enabled.strip().lower() in {"1", "true", "yes", "on"}
    user.llm_enabled = enabled
    db.commit()

    label = "включён" if enabled else "выключен"
    return RedirectResponse(
        url=f"/api/v1/llm/admin?msg=LLM+доступ+{label}+для+{user.username}",
        status_code=303,
    )
