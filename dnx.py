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

# Limitlar
TOTAL_GROUPS = 500
DAILY_GROUPS = 50
DAYS = 10
BATCH_DELAY = 24 * 60 * 60   # 24 soat (sekundlarda)

# Holatlar
ASK_PASSWORD, PHONE, CODE, PASSWORD = range(4)

# Sessions papkasi
Path("sessions").mkdir(exist_ok=True)

# Telegram Client-lar
sessions = {}

# Avtorizatsiya qilingan foydalanuvchilar
authorized_users = set()

# Progress fayllari
def load_progress(phone: str):
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
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    if not phone.startswith("+") or not phone[1:].isdigit():
        await update.message.reply_text("❌ Telefon raqam noto‘g‘ri formatda.")
        return PHONE

    context.user_data["phone"] = phone

    client = TelegramClient(f"sessions/{phone}", api_id, api_hash)
    sessions[user_id] = client
    await client.connect()

    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            await update.message.reply_text("📩 Kod yuborildi, uni kiriting:")
            return CODE
        except Exception as e:
            await update.message.reply_text(f"❌ Kod yuborishda xato: {e}")
            return ConversationHandler.END
    else:
        await update.message.reply_text("✅ Akkount allaqachon avtorizatsiya qilingan. Guruh yaratish jarayoni boshlanadi...")
        asyncio.get_running_loop().create_task(auto_group_task(user_id, client, phone, context))
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
        await update.message.reply_text(f"❌ Kod xato: {e}")
        return ConversationHandler.END

    await update.message.reply_text("✅ Akkount ulandi. Guruh yaratish jarayoni boshlanadi...")
    asyncio.get_running_loop().create_task(auto_group_task(user_id, client, phone, context))
    return ConversationHandler.END

async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = sessions.get(user_id)
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        await update.message.reply_text(f"❌ Parol xato: {e}")
        return ConversationHandler.END

    await update.message.reply_text("✅ Akkount ulandi. Guruh yaratish jarayoni boshlanadi...")
    phone = context.user_data.get("phone")
    asyncio.get_running_loop().create_task(auto_group_task(user_id, client, phone, context))
    return ConversationHandler.END

# 🔥 Guruh yaratish jarayoni
async def auto_group_task(user_id, client, phone, context):
    start_index = load_progress(phone)
    running = True

    while running and start_index < TOTAL_GROUPS:
        end_index = min(start_index + DAILY_GROUPS, TOTAL_GROUPS)

        status_message = await context.bot.send_message(
            user_id,
            f"🚀 {phone} uchun bugungi guruhlar: {start_index+1} - {end_index}\n"
            f"{generate_progress_bar(0, DAILY_GROUPS)}",
        )

        for i in range(start_index + 1, end_index + 1):
            try:
                result = await client(CreateChannelRequest(
                    title=f"Guruh #{i}",
                    about="Avtomatik yaratildi",
                    megagroup=True   # 🔥 Supergroup
                ))
                channel = result.chats[0]

                try:
                    TARGET_BOT = "@oxang_bot"
                    await client(InviteToChannelRequest(channel, [TARGET_BOT]))
                except Exception:
                    pass

                save_progress(phone, i)

                if (i - start_index) % 5 == 0:  # tez-tez edit bo‘lishidan saqlash
                    await status_message.edit_text(
                        f"🚀 {phone} uchun bugungi guruhlar: {start_index+1} - {end_index}\n"
                        f"{generate_progress_bar(i - start_index, DAILY_GROUPS)}"
                    )

            except Exception as e:
                await context.bot.send_message(user_id, f"❌ Guruh #{i} yaratishda xato: {e}")
            await asyncio.sleep(2)

        start_index = end_index
        await context.bot.send_message(user_id, f"✅ {phone} uchun bugungi {DAILY_GROUPS} ta guruh yaratildi.")

        if start_index >= TOTAL_GROUPS:
            await context.bot.send_message(user_id, f"🎉 {phone} uchun barcha {TOTAL_GROUPS} guruh yaratildi!")
            running = False
            break

        # Keyingi kuni davom etadi
        await asyncio.sleep(BATCH_DELAY)

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
            PHONE: [MessageHandler((filters.CONTACT) | (filters.TEXT & ~filters.COMMAND), phone_received)],
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
