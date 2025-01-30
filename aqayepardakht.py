import logging
import json
import sqlite3
import asyncio
import random
import requests
from datetime import datetime, timedelta
import jdatetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import TelegramError

# خواندن تنظیمات از فایل config.json
with open('config.json', 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)

API_TOKEN = config['API_TOKEN']
DB_FILE = config['DB_FILE']
SPONSOR_CHANNELS = config['SPONSOR_CHANNELS']

# تنظیمات لاگینگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ذخیره داده‌های کاربران
user_data = {}

# ====== توابع کمکی ======

def format_price(price):
    """فرمت مبلغ با کاما"""
    return "{:,}".format(price)

def convert_to_tehran_time(utc_time_str):
    """تبدیل زمان UTC به وقت تهران و فرمت شمسی"""
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%d %H:%M:%S")
    tehran_time = utc_time + timedelta(hours=3, minutes=30)
    j_date = jdatetime.datetime.fromgregorian(year=tehran_time.year, month=tehran_time.month, day=tehran_time.day)
    return f"{j_date.year}/{j_date.month}/{j_date.day} {tehran_time.strftime('%H:%M:%S')}"

async def check_membership(user_id, bot):
    """بررسی عضویت کاربر در کانال‌های اسپانسر"""
    for channel in SPONSOR_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except TelegramError:
            return False
    return True

async def send_membership_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام عضویت در کانال‌ها"""
    buttons = [[InlineKeyboardButton(channel['name'], url=f"https://t.me/{channel['id'][1:]}")] for channel in SPONSOR_CHANNELS]
    buttons.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "🔻 برای استفاده از امکانات ربات لطفا در کانال‌های زیر عضو شوید:",
        reply_markup=markup
    )

def init_db():
    """ایجاد دیتابیس و جدول مربوط به فاکتورها"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY,
            transid TEXT,
            amount INTEGER,
            trx_amount REAL,
            wallet TEXT,
            user_id INTEGER,
            status TEXT,
            message_chat_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_invoice(invoice_id, transid, amount, trx_amount, wallet, user_id, status="pending"):
    """ذخیره فاکتور در دیتابیس"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO invoices (invoice_id, transid, amount, trx_amount, wallet, user_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (invoice_id, transid, amount, trx_amount, wallet, user_id, status))
    conn.commit()
    conn.close()

def update_invoice_status(invoice_id, status):
    """به‌روزرسانی وضعیت فاکتور در دیتابیس"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE invoices SET status = ? WHERE invoice_id = ?", (status, invoice_id))
    conn.commit()
    conn.close()

def get_pending_invoices():
    """گرفتن فاکتورهای معلق که بیش از 15 دقیقه از ایجادشان گذشته است"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT invoice_id, user_id FROM invoices
        WHERE status = 'pending' AND created_at <= datetime('now', '-15 minutes')
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_message_chat_id(invoice_id, message_chat_id):
    """به‌روزرسانی message_chat_id برای یک فاکتور"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE invoices SET message_chat_id = ? WHERE invoice_id = ?", (message_chat_id, invoice_id))
    conn.commit()
    conn.close()

async def handle_invoice_cancellation(context, invoice_id, user_id):
    """لغو فاکتور و حذف پیام مربوطه"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT message_chat_id FROM invoices WHERE invoice_id = ?", (invoice_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0]:
        message_chat_id = row[0]
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=message_chat_id)
        except Exception as e:
            logger.error(f"خطا در حذف پیام برای کاربر {user_id}: {e}")

    await context.bot.send_message(
        chat_id=user_id,
        text=f"❌ کاربر گرامی، سفارش شما با شماره {invoice_id} به دلیل عدم پرداخت فاکتور بعد از ۱۵ دقیقه لغو شد."
    )

async def monitor_invoices(context: ContextTypes.DEFAULT_TYPE):
    """بررسی وضعیت فاکتورهای معلق و لغو آنها در صورت عدم پرداخت"""
    while True:
        pending_invoices = get_pending_invoices()
        for invoice_id, user_id in pending_invoices:
            update_invoice_status(invoice_id, "canceled")
            await handle_invoice_cancellation(context, invoice_id, user_id)
        await asyncio.sleep(60)

def generate_invoice_number():
    """تولید شماره فاکتور 8 رقمی"""
    return random.randint(10000000, 99999999)

def get_trx_price():
    """دریافت قیمت لحظه‌ای ترون"""
    try:
        url = "https://api.nobitex.ir/market/stats?srcCurrency=trx&dstCurrency=rls"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            best_buy_price = int(data['stats']['trx-rls']['bestBuy']) // 10
            return best_buy_price
        else:
            raise Exception("API Error")
    except Exception as e:
        logger.error(f"Error fetching TRX price: {e}")
        return None

async def create_invoice(chat_id, trx_amount, fee_method, wallet_address):
    """
    ارسال درخواست به پذیرنده برای صدور فاکتور
    """
    trx_price = get_trx_price()
    if not trx_price:
        return None, "خطا در دریافت قیمت ترون"

    amount_toman = int(trx_amount * trx_price)
    if fee_method == "fee_toman":
        amount_toman = int((trx_amount * 1.05 + 1.5) * trx_price)
    elif fee_method == "fee_trx":
        amount_toman = int((trx_amount * 1.05) * trx_price)

    invoice_number = generate_invoice_number()
    data = {
        "pin": "sandbox",
        "amount": amount_toman,
        "callback": "http://127.0.0.1:5000/callback",
        "invoice_id": str(invoice_number),
    }

    try:
        response = requests.post('https://panel.aqayepardakht.ir/api/v2/create', data=data)
        json_data = response.json()

        if response.status_code == 200 and json_data.get('status') == 'success':
            payment_url = f"https://panel.aqayepardakht.ir/startpay/sandbox/{json_data['transid']}"
            transid = json_data['transid']
            save_invoice(invoice_number, transid, amount_toman, trx_amount, wallet_address, chat_id, "pending")
            return payment_url, invoice_number
        else:
            return None, invoice_number
    except Exception as e:
        logger.error(f"خطا در درخواست به پذیرنده: {e}")
        return None, invoice_number

# ====== هندلرهای دستورات ======

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /start"""
    user_id = update.effective_user.id
    is_member = await check_membership(user_id, context.bot)
    
    if not is_member:
        await send_membership_message(update, context)
        return

    chat_id = update.effective_chat.id
    context.user_data[chat_id] = {"status": "idle"}
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 خرید ترون", callback_data="buy_trx")],
        [
            InlineKeyboardButton("📊 قیمت ترون", callback_data="price_trx"),
            InlineKeyboardButton("📥 درخواست پذیرندگی", callback_data="request_acceptance")
        ],
        [
            InlineKeyboardButton("📩 ارتباط با ما", callback_data="contact_us"),
            InlineKeyboardButton("🧾 لیست تراکنش‌ها", callback_data="list_transactions")
        ],
    ])
    await update.message.reply_text(
        "به ربات خوش آمدید! لطفاً از منوی زیر انتخاب کنید:",
        reply_markup=markup
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌ها"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    is_member = await check_membership(user_id, context.bot)
    
    if not is_member and query.data != "check_membership":
        await send_membership_message(update, context)
        return

    if query.data == "check_membership":
        is_member = await check_membership(user_id, context.bot)
        if is_member:
            await query.message.delete()
            await start_handler(update, context)
        else:
            await query.message.reply_text("❌ شما هنوز عضو همه کانال‌ها نشده‌اید. لطفاً عضو شوید و دوباره تلاش کنید.")
        return

    user_status = user_data.get(query.message.chat.id, {}).get("status", "idle")

    if query.data == "price_trx":
        trx_price = get_trx_price()
        if trx_price:
            formatted_price = format_price(trx_price)
            current_time = datetime.now().strftime("%H:%M")
            await query.message.reply_text(
                f"📊 قیمت هر واحد ترون: {formatted_price} تومان\n🕘 آخرین بروزرسانی: ساعت {current_time}"
            )
        else:
            await query.message.reply_text(
                "خطا در دریافت قیمت از API. لطفاً دوباره تلاش کنید."
            )
        await query.message.delete()

    elif query.data == "buy_trx":
        if user_status not in ["idle"]:
            await query.message.reply_text("❌ شما در حال انجام عملیات دیگری هستید. لطفاً ابتدا عملیات را لغو کنید.")
        else:
            user_data[query.message.chat.id] =
