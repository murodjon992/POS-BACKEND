import random
from django.core.management.base import BaseCommand
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import CallbackQueryHandler
from django.conf import settings
from asgiref.sync import sync_to_async
from posapp.models import Subscription

GURUH_ID = "@barakapos"
# 1. START KOMANDASI

async def check_membership(context, user_id):
    """Foydalanuvchi kanal va guruhga a'zoligini tekshirish"""
    try:

        # Guruhni tekshirish
        guruh_member = await context.bot.get_chat_member(chat_id=GURUH_ID, user_id=user_id)

        allowed = ['member', 'administrator', 'creator']
        return  guruh_member.status in allowed
    except Exception as e:
        print(f"Tekshirishda xato: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if args:
        context.user_data['attempt_user_id'] = args[0]

        # A'zolikni tekshiramiz
        is_member = await check_membership(context, user_id)

        if not is_member:
            keyboard = [
                [InlineKeyboardButton("💬 Guruhga qo'shilish", url="https://t.me/barakapos")],
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data="check_sub")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Botdan foydalanish uchun avval guruhimizga qo'shiling guruhda shikoyat va takliflar bildirishingiz mumkin:",
                reply_markup=reply_markup
            )
            return

        # Agar a'zo bo'lsa, kontakt so'rash tugmasini chiqaramiz
        await show_contact_button(update)
    else:
        await update.message.reply_text("Iltimos, ilovadagi tugma orqali kiring.")

async def show_contact_button(update):
    contact_button = KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Rahmat! Endi telefon raqamingizni yuborishingiz mumkin:",
        reply_markup=reply_markup
    )

async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if await check_membership(context, user_id):
        await query.message.delete() # Eski xabarni o'chirish
        await show_contact_button(query)
    else:
        await query.message.reply_text("❌ Hali ham guruhga a'zo emassiz!")


# 2. KONTAKTNI QABUL QILISH VA TEKSHIRISH
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    telegram_phone = contact.phone_number.replace('+', '').strip()
    chat_id = update.effective_chat.id

    target_user_id = context.user_data.get('attempt_user_id')

    if not target_user_id:
        await update.message.reply_text("❌ Xatolik: Jarayon boshidan boshlanmadi. Ilovadan qayta kiring.")
        return

    # Bazadan User ID orqali Subscriptionni qidiramiz
    sub = await sync_to_async(
        lambda: Subscription.objects.select_related('user').filter(user_id=target_user_id).first()
    )()

    if sub:
        # XAVFSIZLIK SHARTI: Ilovadagi raqam Telegram raqami bilan bir xilmi?
        if sub.phone == telegram_phone:
            sub.telegram_chat_id = chat_id
            await sync_to_async(sub.save)()

            await update.message.reply_text(
                f"✅ Tasdiqlandi! {sub.user.username}, raqamlar mos keldi.\n"
                "Endi ilovaga qaytib 'Kodni yuborish' tugmasini bosishingiz mumkin."
            )
            context.user_data.clear()
        else:
            await update.message.reply_text(
                f"❌ Raqamlar mos emas!\n"
                f"Ilovadagi raqam: +{sub.phone}\n"
                f"Siz yuborgan raqam: +{telegram_phone}\n\n"
                "Faqat o'z raqamingizga tegishli Telegramdan foydalaning."
            )
    else:
        await update.message.reply_text("❌ Foydalanuvchi topilmadi.")


# 3. DJANGO COMMAND KLASSI (Xato shu yerda edi)
class Command(BaseCommand):
    help = 'Telegram botni yurgizish (Polling)'

    def handle(self, *args, **options):
        print("Bot ishga tushdi...")

        # Bot tokenini settings'dan oladi
        app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

        # Handlerlarni qo'shamiz
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(check_callback, pattern="check_sub"))
        app.add_handler(MessageHandler(filters.CONTACT, handle_contact))

        # Botni yurgizamiz
        app.run_polling()