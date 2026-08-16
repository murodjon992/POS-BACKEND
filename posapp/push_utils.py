# posapp/push_utils.py - YANGI FAYL, shu nom bilan yarating (models.py bilan bir papkada)

import requests
from .models import PushToken

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_push_notification(user, title, body, data=None):
    """
    Berilgan userning barcha ro'yxatdan o'tgan qurilmalariga push notification yuboradi.
    Xato bo'lsa jim (silent) qoladi - push kelmasligi asosiy funksionallikni buzmasligi kerak.
    """
    tokens = list(PushToken.objects.filter(user=user).values_list('token', flat=True))
    if not tokens:
        return

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

        # Agar qurilma ilovani o'chirib tashlagan/tokendan voz kechgan bo'lsa,
        # Expo shuni bildiradi - o'sha tokenni bazadan o'chirib tashlaymiz
        for item, token in zip(result.get("data", []), tokens):
            if item.get("status") == "error" and item.get("details", {}).get("error") == "DeviceNotRegistered":
                PushToken.objects.filter(token=token).delete()

    except Exception as e:
        print(f"Push notification yuborishda xato: {e}")