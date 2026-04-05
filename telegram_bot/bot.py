import requests
from django.conf import settings


def send_telegram_otp(chat_id, otp_code):
    token = settings.TELEGRAM_BOT_TOKEN
    message = f"🔒 Parolni tiklash kodi: {otp_code}\n\nHech kimga bermang!"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, data=payload)
        return response.json()
    except Exception as e:
        print(f"Telegram xatosi: {e}")
        return None