from celery import shared_task
from django.utils import timezone
from .models import Subscription, StocLog # Sale modelingiz bor deb faraz qilamiz
import requests
from django.conf import settings
from django.db.models import Sum

@shared_task
def send_daily_reports():
    today = timezone.now().date()
    # Telegram ID si bor va obunasi faol ownerlarni olamiz
    active_subs = Subscription.objects.filter(
        telegram_chat_id__isnull=False, 
        is_active_status=True
    ).select_related('user')

    token = settings.TELEGRAM_BOT_TOKEN
    
    for sub in active_subs:
        # O'sha ownerga tegishli bugungi savdolarni hisoblash
        # Diqqat: Sale modelida 'owner' yoki 'user' va 'created_at' maydonlari bo'lishi kerak
        daily_sales = StocLog.objects.filter(
            owner=sub.user, 
            created_at__date=today
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        msg = (
            f"📊 <b>Kunlik hisobot ({today}):</b>\n\n"
            f"👤 Do'kon: {sub.user.username}\n"
            f"💰 Bugungi jami savdo: {daily_sales:,.0f} so'm\n"
            f"📅 Obuna muddati: {sub.days_left} kun qoldi."
        )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": sub.telegram_chat_id, "text": msg, "parse_mode": "HTML"})