from celery import shared_task
from datetime import timedelta
import requests
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, F, DecimalField, Value
from django.db import transaction as db_transaction
from django.db.models.functions import Coalesce
import pytz

from .models import Subscription, SupplierLog, Transaction, Supplier, Customer, AccessoryInventory
from .push_utils import send_push_notification  # <-- YANGI IMPORT


@shared_task
def send_daily_reports():
    print("🚀 Celery Task ishga tushdi (Har 30 sekundda)...")

    tashkent_tz = pytz.timezone('Asia/Tashkent')
    now_tashkent = timezone.now().astimezone(tashkent_tz)
    today = now_tashkent.date()

    active_subs = Subscription.objects.filter(
        telegram_chat_id__isnull=False
    ).select_related('user')

    if not active_subs.exists():
        print("⚠️ Diqqat! Bazada 'telegram_chat_id' kiritilgan birorta ham obunachi topilmadi!")
        return

    token = settings.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    decimal_zero = Value(0, output_field=DecimalField())

    for sub in active_subs:
        actual_owner = sub.user
        print(f"📊 {actual_owner.username} uchun ma'lumotlar hisoblanmoqda...")

        try:
            seyf_qs = Transaction.objects.filter(owner=actual_owner, payment_method='cash')

            seyf_kirim = seyf_qs.filter(
                type__in=['sale', 'customer_pay', 'income']
            ).aggregate(s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero))['s']

            seyf_chiqim = seyf_qs.filter(
                type__in=['supplier_pay', 'expense', 'return_sale']
            ).aggregate(s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero))['s']

            safe_balance = seyf_kirim - seyf_chiqim

            start_of_day = tashkent_tz.localize(timezone.datetime(today.year, today.month, today.day, 0, 0, 0))
            end_of_day = start_of_day + timedelta(days=1)

            daily_tx = Transaction.objects.filter(
                owner=actual_owner,
                created_at__range=(start_of_day, end_of_day)
            )

            daily_sales = daily_tx.filter(type='sale').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_returns = daily_tx.filter(type='return_sale').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_total_sales = daily_sales - daily_returns

            daily_cash_sales = daily_tx.filter(type='sale', payment_method='cash').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_customer_payments = daily_tx.filter(type='customer_pay', payment_method='cash').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_cash_in = daily_cash_sales + daily_customer_payments

            total_supplier_debt = Supplier.objects.filter(owner=actual_owner).aggregate(
                s=Coalesce(Sum('total_debt_to_them', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_supplier_new_debt = SupplierLog.objects.filter(
                supplier__owner=actual_owner,
                type='take',
                created_at__range=(start_of_day, end_of_day)
            ).aggregate(s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero))['s']

            daily_supplier_return = SupplierLog.objects.filter(
                supplier__owner=actual_owner, type='return', created_at__range=(start_of_day, end_of_day)
            ).aggregate(s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero))['s']

            daily_supplier_pay = daily_tx.filter(type='supplier_pay').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            total_customer_debt = Customer.objects.filter(owner=actual_owner).aggregate(
                s=Coalesce(Sum('total_debt', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_new_debt = daily_tx.filter(type='sale', payment_method='debt').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_debt_collected = daily_tx.filter(type='customer_pay').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']

            daily_expenses = daily_tx.filter(type='expense').aggregate(
                s=Coalesce(Sum('amount', output_field=DecimalField()), decimal_zero)
            )['s']
            expense_qs = daily_tx.filter(type='expense').order_by('-created_at')
            expense_text = ""
            if expense_qs.exists():
                expense_text = "\n<b>Chiqimlar batafsil:</b>\n"
                for exp in expense_qs:
                    local_created_at = exp.created_at.astimezone(tashkent_tz)
                    time_str = local_created_at.strftime("%H:%M")
                    note_str = exp.note if exp.note else "Izohsiz"
                    expense_text += f" • {time_str} - {exp.amount:,.0f} so'm ({note_str})\n"

            inventory_value = AccessoryInventory.objects.filter(product__owner=actual_owner).aggregate(
                total=Coalesce(Sum(F('quantity') * F('product__purchase_price'), output_field=DecimalField()), decimal_zero)
            )['total']

            msg = (
                f"📊 <b>KUNLIK MOLIYAVIY HISOBOT</b>\n"
                f"📅 <b>Sana:</b> {today}\n"
                f"👤 <b>Do'kon:</b> {actual_owner.username}\n"
                f"───────────────────\n\n"

                f"💰 <b>SAVDO VA KASSA:</b>\n"
                f"• <b>Jami Sof Savdo:</b> <code>{daily_total_sales:,.0f} so'm</code>\n"
                f"  <i>(Sotuv: {daily_sales:,.0f} | Vozvrat: {daily_returns:,.0f})</i>\n"
                f"• <b>Kassaga Naqd Kirim:</b> <code>{daily_cash_in:,.0f} so'm</code>\n"
                f"  <i>(Naqd savdo: {daily_cash_sales:,.0f} | Qarz to'lovi: {daily_customer_payments:,.0f})</i>\n\n"

                f"👥 <b>MIJOZLAR (NASIYA):</b>\n"
                f"• <b>Bugun berilgan qarz:</b> <code>{daily_new_debt:,.0f} so'm</code>\n"
                f"• <b>Bugun qaytgan qarz:</b> <code>{daily_debt_collected:,.0f} so'm</code>\n"
                f"• 🔴 <b>Jami mijozlar qarzi:</b> <code>{total_customer_debt:,.0f} so'm</code>\n\n"

                f"🏢 <b>TA'MINOTCHILAR (SUPPLIER):</b>\n"
                f"• <b>Bugun olingan yuk (nasiya):</b> <code>{daily_supplier_new_debt:,.0f} so'm</code>\n"
                f"• <b>Bugun qaytarilgan yuk:</b> <code>{daily_supplier_return:,.0f} so'm</code>\n"
                f"• <b>Bugun to'langan pul:</b> <code>{daily_supplier_pay:,.0f} so'm</code>\n"
                f"• 🧮 <b>Jami ta'minotchilardan qarz:</b> <code>{total_supplier_debt:,.0f} so'm</code>\n\n"

                f"💸 <b>CHIQIMLAR VA SEYF:</b>\n"
                f"• <b>Bugun jami chiqim:</b> <code>{daily_expenses:,.0f} so'm</code>\n"
                f"{expense_text}\n"
                f"🗄️ <b>Seyfdagi jami naqd pul:</b> <b><u>{safe_balance:,.0f} so'm</u></b>\n\n"

                f"📦 <b>OMBOR STATUSI:</b>\n"
                f"• <i>Ombor balansi (Tan narxda):</i> <code>{inventory_value:,.0f} so'm</code>\n"
                f"───────────────────\n"
                f"📅 <i>Sizda {sub.days_left} kunlik faol obuna mavjud.</i>"
            )

            res = requests.post(
                url,
                data={"chat_id": sub.telegram_chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )
            print(f"🤖 Bot javobi: Status {res.status_code}")

            # YANGI: qisqa push eslatma - to'liq hisobot emas, faqat diqqat tortish uchun
            send_push_notification(
                actual_owner,
                "Kunlik hisobot tayyor",
                f"Bugungi savdo: {daily_total_sales:,.0f} so'm. Batafsili Telegram botda."
            )

        except Exception as telegram_err:
            print(f"❌ Xatolik yuz berdi ({actual_owner.username}): {str(telegram_err)}")


@shared_task
def check_expired_subscriptions():
    print("🔔 Muddati tugagan obunalarni tekshirish boshlandi...")

    now = timezone.now()
    yesterday = now - timedelta(days=1)

    expired_subs = Subscription.objects.filter(
        trial_end__lt=now,
        trial_end__gte=yesterday,
    ).select_related('user')

    for sub in expired_subs:
        send_push_notification(
            sub.user,
            "Obuna muddati tugadi",
            "Obunangiz muddati tugadi. Ishlashni davom ettirish uchun tarifni yangilang."
        )
        print(f"🔔 {sub.user.username} ga muddat tugashi haqida push yuborildi.")