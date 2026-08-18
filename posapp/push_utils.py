# posapp/push_utils.py

import logging
import requests
from .models import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_push_notification(user, title, body, data=None):
    """
    Berilgan userning barcha ro'yxatdan o'tgan qurilmalariga push notification yuboradi.
    """
    logger.warning(f"[PUSH] send_push_notification chaqirildi: user={user.username}")

    tokens = list(PushToken.objects.filter(user=user).values_list('token', flat=True))
    if not tokens:
        logger.warning(f"[PUSH] {user.username} uchun hech qanday token topilmadi - yuborilmadi.")
        return

    logger.warning(f"[PUSH] {len(tokens)} ta tokenga yuborilyapti: {tokens}")

    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data or {},
        }
        for token in tokens
    ]

    try:
        response = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        result = response.json()
        logger.warning(f"[PUSH] Expo javobi: {result}")

        for item, token in zip(result.get("data", []), tokens):
            if item.get("status") == "error" and item.get("details", {}).get("error") == "DeviceNotRegistered":
                PushToken.objects.filter(token=token).delete()
                logger.warning(f"[PUSH] Yaroqsiz token o'chirildi: {token}")

    except Exception as e:
        logger.error(f"[PUSH] Push notification yuborishda xato: {e}")