"""
Клиент Novu Cloud: FCM device tokens (PATCH credentials) и trigger workflow для push.
Документация: https://docs.novu.co/platform/integrations/push/fcm
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from server.settings import settings

logger = logging.getLogger(__name__)


def is_novu_configured() -> bool:
    return bool(settings.NOVU_SECRET_KEY)


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"ApiKey {settings.NOVU_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _novu_http_hint(status_code: int, text: str, limit: int = 450) -> str:
    snippet = (text or "").replace("\n", " ").strip()[:limit]
    if snippet:
        return f"Novu HTTP {status_code}: {snippet}"
    return f"Novu HTTP {status_code}"


async def _ensure_subscriber(client: httpx.AsyncClient, subscriber_id: str) -> None:
    url = f"{settings.NOVU_API_URL}/v1/subscribers"
    try:
        r = await client.post(
            url,
            headers=_headers(),
            json={"subscriberId": subscriber_id},
        )
    except httpx.RequestError as e:
        logger.exception("Novu create subscriber request failed: %s url=%s", e, url)
        return
    if r.status_code in (200, 201):
        return
    if r.status_code == 409:
        return
    logger.warning(
        "Novu create subscriber %s: HTTP %s %s",
        subscriber_id,
        r.status_code,
        (r.text or "")[:400],
    )


async def upsert_fcm_device_tokens(
    subscriber_id: str, device_tokens: List[str]
) -> Tuple[bool, Optional[str]]:
    """
    Сохранить FCM-токены подписчика в Novu (provider fcm).
    Возвращает (ok, hint): hint — краткая причина для ответа API при ok=False.
    """
    if not is_novu_configured() or not device_tokens:
        return False, "Novu not configured or empty token list"

    body: Dict[str, Any] = {
        "providerId": "fcm",
        "credentials": {"deviceTokens": device_tokens},
    }
    if settings.NOVU_FCM_INTEGRATION_IDENTIFIER:
        body["integrationIdentifier"] = settings.NOVU_FCM_INTEGRATION_IDENTIFIER

    url = f"{settings.NOVU_API_URL}/v1/subscribers/{subscriber_id}/credentials"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                r = await client.patch(url, headers=_headers(), json=body)
            except httpx.RequestError as e:
                logger.exception(
                    "Novu FCM PATCH failed (network): %s url=%s api=%s",
                    e,
                    url,
                    settings.NOVU_API_URL,
                )
                return False, f"Cannot reach Novu ({settings.NOVU_API_URL}): {type(e).__name__}: {e}"
            if r.status_code in (200, 201, 204):
                logger.info("Novu FCM credentials updated for subscriber %s", subscriber_id)
                return True, None
            if r.status_code == 404:
                await _ensure_subscriber(client, subscriber_id)
                try:
                    r2 = await client.patch(url, headers=_headers(), json=body)
                except httpx.RequestError as e:
                    logger.exception("Novu FCM PATCH retry failed (network): %s", e)
                    return False, f"Novu network error on retry: {type(e).__name__}: {e}"
                if r2.status_code in (200, 201, 204):
                    logger.info(
                        "Novu FCM credentials updated for subscriber %s (after create)",
                        subscriber_id,
                    )
                    return True, None
                hint = _novu_http_hint(r2.status_code, r2.text)
                logger.warning(
                    "Novu FCM credentials (retry): HTTP %s %s",
                    r2.status_code,
                    (r2.text or "")[:400],
                )
                return False, hint
            hint = _novu_http_hint(r.status_code, r.text)
            logger.warning(
                "Novu FCM credentials: HTTP %s %s",
                r.status_code,
                (r.text or "")[:400],
            )
            return False, hint
    except Exception as e:
        logger.exception("Novu FCM credentials unexpected error: %s", e)
        return False, f"{type(e).__name__}: {e}"


async def trigger_new_message_push(
    recipient_subscriber_id: str,
    *,
    message_id: str,
    room_id: Optional[str],
    sender_display_name: str,
    type_message: str = "Новое сообщение",
) -> None:
    """
    Запуск workflow push для получателя.
    type_message: строка для payload.typeMessage (в типичном шаблоне Novu — текст уведомления / тело).
    FCM override: title = senderName, body = typeMessage — как у сообщений чата.
    """
    if not is_novu_configured():
        logger.warning(
            "Novu push skipped: NOVU_SECRET_KEY is empty (trigger not sent, subscriber=%s)",
            recipient_subscriber_id[:8],
        )
        return
    if not settings.NOVU_PUSH_TRIGGER_IDENTIFIER:
        logger.warning(
            "Novu push skipped: NOVU_PUSH_TRIGGER_IDENTIFIER is empty (trigger not sent, subscriber=%s)",
            recipient_subscriber_id[:8],
        )
        return

    sender_display_name = (sender_display_name or "").strip()
    type_label = (type_message or "").strip() or "Новое сообщение"

    # Шаблон Novu: senderName, typeMessage (человекочитаемо), appName.
    title = sender_display_name or "Контакт"
    payload: Dict[str, Any] = {
        "senderName": title,
        "typeMessage": type_label,
        "appName": settings.NOVU_PUSH_APP_NAME,
        "messageId": message_id,
        "roomId": room_id or "",
    }

    url = f"{settings.NOVU_API_URL}/v1/events/trigger"
    # Явный title/body для FCM (как в шаблоне Novu для сообщений): title = senderName, body = typeMessage.
    # См. Novu: workflow-level overrides → providers.fcm.notification.
    overrides: Dict[str, Any] = {
        "providers": {
            "fcm": {
                "notification": {
                    "title": title,
                    "body": type_label,
                }
            }
        }
    }
    # Выбор инстанса FCM при отправке (несколько интеграций Push в одном environment).
    # См. Novu: overrides.push.integrationIdentifier (актуально для self-hosted / новых версий API).
    ident = (settings.NOVU_FCM_INTEGRATION_IDENTIFIER or "").strip()
    if ident:
        overrides["push"] = {"integrationIdentifier": ident}

    body: Dict[str, Any] = {
        "name": settings.NOVU_PUSH_TRIGGER_IDENTIFIER,
        "to": {"subscriberId": recipient_subscriber_id},
        "payload": payload,
        "overrides": overrides,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, headers=_headers(), json=body)
        if r.status_code in (200, 201):
            logger.info(
                "Novu trigger OK: workflow=%s subscriber=%s message_id=%s api=%s fcm_integration=%s",
                settings.NOVU_PUSH_TRIGGER_IDENTIFIER,
                recipient_subscriber_id[:8] + "...",
                str(message_id)[:8] + "...",
                settings.NOVU_API_URL,
                ident or "(default)",
            )
            return
        logger.warning(
            "Novu trigger failed: workflow=%s HTTP %s %s (api=%s)",
            settings.NOVU_PUSH_TRIGGER_IDENTIFIER,
            r.status_code,
            (r.text or "")[:500],
            settings.NOVU_API_URL,
        )
