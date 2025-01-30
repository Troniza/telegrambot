import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import requests
from datetime import datetime, timedelta
import random
import sqlite3
import asyncio
import jdatetime
import json

# خواندن اطلاعات پیکربندی از فایل config.json
with open('config.json', 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)

# ====== پیکربندی ======
TOKEN = config['token']
SPONSOR_CHANNELS = config['sponsor_channels']
DB_FILE = config['invoices']
USERS_DB = config['users']

# ذخیره داده‌های کاربران
user_data = {}

# تنظیمات لاگینگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== توابع کمکی ======

async def check_membership(bot, user_id):
    for channel in SPONSOR_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception:
            return False
    return True

async def send_sponsor_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = []
    for channel in SPONSOR_CHANNELS:
        keyboard.append([InlineKeyboardButton(channel['name'], url=channel['link'])])
    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data='check_membership')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔻 برای استفاده از امکانات ربات لطفا در کانال‌های زیر عضو شوید:",
        reply_markup=reply_markup
    )

def format_price(price):
    """فرمت مبلغ با کاما"""
    return "{:,}".format(price)

def convert_to_tehran_time(utc_time_str):
    """تبدیل زمان UTC به وقت تهران و فرمت شمسی"""
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%d %H:%M:%S")
    tehran_time = utc_time + timedelta(hours=3, minutes=30)
    
    # تبدیل تاریخ به شمسی
    j_date = jdatetime.datetime.fromgregorian(year=tehran_time.year, month=tehran_time.month, day=tehran_time.day)
    return f"{j_date.year}/{j_date.month}/{j_date.day} {tehran_time.strftime('%H:%M:%S')}"  # فرمت تاریخ شمسی

async def list_transactions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT invoice_id, status, created_at FROM invoices WHERE user_id = ?", (user_id,))
    transactions = cursor.fetchall()
    conn.close()
    
    total_transactions = len(transactions)
    if total_transactions == 0:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("شما هیچ تراکنشی ندارید.")
        return

    page = int(context.user_data.get(f'page_{user_id}', 0))
    items_per_page = 6
    start_index = page * items_per_page
    end_index = start_index + items_per_page

    transactions_sorted = sorted(transactions, key=lambda x: x[2], reverse=True)
    transactions_to_display = transactions_sorted[start_index:end_index]

    keyboard = []
    for i in range(0, len(transactions_to_display), 2):
        row_buttons = []
        for j in range(2):
            if i + j < len(transactions_to_display):
                invoice_id, status, _ = transactions_to_display[i + j]
                button_text = f"🔴 {invoice_id}" if status == 'canceled' else f"🟡 {invoice_id}" if status == 'pending' else f"🟢 {invoice_id}"
                row_buttons.append(InlineKeyboardButton(button_text, callback_data=f"view_{invoice_id}"))
        if row_buttons:
            keyboard.append(row_buttons)

    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton("صفحه قبل ⬅️", callback_data="prev_page"))
    if end_index < total_transactions:
        navigation_buttons.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data="next_page"))

    if navigation_buttons:
        keyboard.append(navigation_buttons)

    markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🧾 لیست تراکنش‌های شما:", reply_markup=markup)

async def view_transaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت جزئیات تراکنش"""
    invoice_id = update.callback_query.data.split("_")[1]  # استخراج invoice_id از callback_data
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # دریافت جزئیات تراکنش
    cursor.execute("SELECT transid, amount, trx_amount, wallet, status, created_at FROM invoices WHERE invoice_id = ?", (invoice_id,))
    transaction = cursor.fetchone()
    conn.close()
    
    if transaction:
        transid, amount, trx_amount, wallet, status, created_at = transaction
        
        # تبدیل زمان به وقت تهران
        created_at_tehran = convert_to_tehran_time(created_at)
        
        # وضعیت تراکنش
        status_icon = "🔴" if status == "canceled" else "🟢" if status == "paid" else "🟡"
        status_text = "لغو شده" if status == "canceled" else "موفق" if status == "paid" else "معلق"
        
        response_text = f"✅ جزئیات تراکنش شما با شماره {invoice_id}:\n\n" \
                        f"کد تراکنش: {transid}\n" \
                        f"مبلغ(تومان): {format_price(amount)}\n" \
                        f"تعداد ترون: {trx_amount}\n" \
                        f"آدرس ولت: {wallet}\n" \
                        f"وضعیت: {status_icon} {status_text}\n" \
                        f"\n" \
                        f"تاریخ: {created_at_tehran}"
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(response_text)
    else:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("تراکنش یافت نشد.")

async def navigation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت ناوبری بین صفحات"""
    user_id = update.effective_chat.id
    current_page = int(context.user_data.get(f'page_{user_id}', 0))

    if update.callback_query.data == "next_page":
        context.user_data[f'page_{user_id}'] = current_page + 1
    elif update.callback_query.data == "prev_page":
        context.user_data[f'page_{user_id}'] = current_page - 1

    await list_transactions_handler(update, context)

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
            message_chat_id INTEGER
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def init_user_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        role INTEGER DEFAULT 1,
        phone_number TEXT,
        card_number TEXT
    )
    ''')
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

async def edit_card_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    await update.callback_query.answer()
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو", callback_data="cancel")]
    ])
    
    await update.callback_query.message.reply_text(
        "☑️ لطفاً شماره کارت 16 رقمی جدید خود را ارسال نمایید:\n"
        "(حتماً صاحب حساب با شماره موبایل تطابق داشته باشد.)",
        reply_markup=markup
    )
    
    context.user_data['registration_step'] = 'edit_card'


def get_pending_invoices():
    """گرفتن فاکتورهای معلق که بیش از 15 دقیقه از ایجادشان گذشته است"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT invoice_id, user_id FROM invoices
        WHERE status = 'pending' AND created_at <= datetime('now', '-1 minutes')
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
        logger.info(f"پیام با ID {message_chat_id} برای حذف پیدا شد.")
        try:
            # حذف پیام
            await context.bot.delete_message(chat_id=user_id, message_id=message_chat_id)
        except Exception as e:
            logger.error(f"خطا در حذف پیام برای کاربر {user_id}: {e}")
    else:
        logger.warning(f"پیام با ID {invoice_id} پیدا نشد یا message_chat_id خالی است.")

    if row and row[0]:
        message_chat_id = row[0]
        try:
            # حذف پیام
            await context.bot.delete_message(chat_id=user_id, message_id=message_chat_id)
        except Exception as e:
            logger.error(f"خطا در حذف پیام برای کاربر {user_id}: {e}")

    # ارسال پیام لغو به کاربر
    await context.bot.send_message(
        chat_id=user_id,
        text=f"❌ کاربر گرامی، سفارش شما با شماره {invoice_id} به دلیل عدم پرداخت فاکتور بعد از ۱۵ دقیقه لغو شد."
    )

# ====== زمان‌بندی ======
async def monitor_invoices(context: ContextTypes.DEFAULT_TYPE):
    """بررسی وضعیت فاکتورهای معلق و لغو آنها در صورت عدم پرداخت"""
    while True:
        pending_invoices = get_pending_invoices()
        for invoice_id, user_id in pending_invoices:
            update_invoice_status(invoice_id, "canceled")
            await handle_invoice_cancellation(context, invoice_id, user_id)
        await asyncio.sleep(60)  # هر 60 ثانیه بررسی انجام شود

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

def format_price(price):
    return "{:,}".format(price)

# ====== هندلرهای دستورات ======


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /start"""
    # تشخیص نوع آپدیت (پیام یا دکمه)
    if update.message:
        chat_id = update.effective_chat.id
        message = update.message
    elif update.callback_query:
        chat_id = update.callback_query.message.chat_id
        message = update.callback_query.message
    else:
        logger.error("Unhandled update type.")
        return

    # بررسی عضویت کاربر
    user_id = update.effective_user.id
    if not await check_membership(context.bot, user_id):
        await send_sponsor_message(update, context)
        return

  # بررسی وجود کاربر در دیتابیس
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user is None:
        # کاربر جدید است، شروع فرآیند احراز هویت
        context.user_data['status'] = 'phone'
        keyboard = [[KeyboardButton("ارسال شماره تماس", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "📲 به جهت احرازهویت لطفاً شماره موبایل خود را ارسال نمایید:",
            reply_markup=reply_markup
        )
    else:
        # کاربر قبلاً ثبت‌نام کرده است، نمایش منوی اصلی
        await show_main_menu(update, context)
    
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if contact.user_id != update.effective_user.id:
        await update.message.reply_text("❌ لطفاً فقط شماره تماس خود را ارسال کنید.")
        return
    
    if not contact.phone_number.startswith("98"):
        await update.message.reply_text("❌ شماره تماس باید با پیش‌شماره +98 شروع شود. لطفاً شماره صحیح را وارد کنید.")
        return

    context.user_data['phone_number'] = contact.phone_number
    context.user_data['status'] = 'card'
    await update.message.reply_text(
        "☑️ لطفاً شماره کارت 16رقمی خود را ارسال نمایید:\n"
        "(حتماً صاحب حساب با شماره موبایل تطابق داشته باشد.)",
        reply_markup=ReplyKeyboardRemove()
    )

async def handle_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    card_number = update.message.text.replace(" ", "")
    if not card_number.isdigit() or len(card_number) != 16:
        await update.message.reply_text("❌ شماره کارت نامعتبر است. لطفاً یک شماره کارت 16 رقمی وارد کنید.")
        return
    
    user_id = update.effective_user.id
    phone_number = context.user_data['phone_number']
    
    # ذخیره اطلاعات کاربر در دیتابیس
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, phone_number, card_number) VALUES (?, ?, ?)",
                   (user_id, phone_number, card_number))
    conn.commit()
    conn.close()
    
    del context.user_data['status']
    await update.message.reply_text("✅ ثبت‌نام شما با موفقیت انجام شد.")
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # بررسی نوع آپدیت
    if update.message:
        chat_id = update.effective_chat.id
    elif update.callback_query:
        chat_id = update.callback_query.message.chat.id
    else:
        logger.error("Unhandled update type.")
        return

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 خرید ترون", callback_data="buy_trx")],
        [
            InlineKeyboardButton("📊 قیمت ترون", callback_data="price_trx"),
            InlineKeyboardButton("📥 درخواست پذیرندگی", callback_data="request_acceptance")
        ],
        [
            InlineKeyboardButton("📩 ارتباط با ما", callback_data="contact_us"),
            InlineKeyboardButton("👤 اطلاعات کاربری", callback_data="user_info")
        ],
    ])

    # ارسال پیام به کاربر
    await context.bot.send_message(
        chat_id=chat_id,
        text="به ربات خوش آمدید! لطفاً از منوی زیر انتخاب کنید:",
        reply_markup=markup
    )

def get_card_number(user_id):
    """گرفتن شماره کارت کاربر از دیتابیس"""
    conn = sqlite3.connect(USERS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT card_number FROM users WHERE user_id = ?", (user_id,))
    card_number = cursor.fetchone()
    conn.close()
    return card_number[0] if card_number else Non

async def create_invoice(chat_id, trx_amount, fee_method, wallet_address):
    """
    ارسال درخواست به پذیرنده برای صدور فاکتور
    """
    # محاسبه مبلغ به تومان
    trx_price = get_trx_price()
    if not trx_price:
        return None, "خطا در دریافت قیمت ترون"

    amount_toman = int(trx_amount * trx_price)  # مبلغ کل به تومان
    if fee_method == "fee_toman":
        amount_toman = int((trx_amount * 1.05 + 1.5) * trx_price)  # با اضافه‌کردن کارمزد
    
    elif fee_method == "fee_trx":
        amount_toman = int((trx_amount * 1.05) * trx_price)

    user_id = chat_id 
    card_number = get_card_number(user_id)

    # داده‌های درخواست
    invoice_number = generate_invoice_number()  # شماره فاکتور
    data = {
        "pin": "sandbox",  # مقدار PIN واقعی را وارد کنید
        "amount": amount_toman,
        "callback": "http://127.0.0.1:5000/callback",
        "invoice_id": str(invoice_number),
        "card_number": card_number
    }

    # ارسال درخواست به API پذیرنده
    try:
        response = requests.post('https://panel.aqayepardakht.ir/api/v2/create', data=data)
        json_data = response.json()

        if response.status_code == 200 and json_data.get('status') == 'success':
            payment_url = f"https://panel.aqayepardakht.ir/startpay/sandbox/{json_data['transid']}"
            transid = json_data['transid']
            # ذخیره فاکتور در دیتابیس
            save_invoice(invoice_number, transid, amount_toman, trx_amount, wallet_address, chat_id, "pending")
            return payment_url, invoice_number
        else:
            return None, invoice_number
    except Exception as e:
        logger.error(f"خطا در درخواست به پذیرنده: {e}")
        return None, invoice_number

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌ها"""
    query = update.callback_query
    await query.answer()

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
            user_data[query.message.chat.id] = {"status": "reading_rules"}
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ قوانین را مطالعه و تایید می‌کنم", callback_data="accept_rules")]
            ])
            await query.message.reply_text(
                "نکات مهم در خرید:\n\n"
                "🔹 بعد از صدور فاکتور فقط ۱۵دقیقه امکان پرداخت وجود دارد، بعد از آن منقضی و درصورت پرداخت نیز وجه به حساب شما باز خواهد گشت.\n"
                "🔹 درهنگام پرداخت باید صاحب حساب با شماره موبایل تایید شده در ربات همخوانی داشته باشد، در غیراینصورت تراکن شما با خطا مواجه خواهد شد.\n"
                "🔹 به طور کلی در ترون استار ۲ روش برای پرداخت کارمزد انتقال شبکه ترون وجود دارد:\n"
                "۱- کارمزد انتقال شبکه به فاکتور شما اضافه می‌شود و شما مقدار ترون وارد شده را به طور کامل دریافت خواهید کرد.\n"
                "۲- کارمزد انتقال شبکه از مقدار ترون شما کسر خواهد شد. به طور مثال در این روش شما ۲۰ترون خریداری کردید و با احتساب کارمزد ۱۸.۵ ترون دریافت خواهید کرد.\n"
                "🔹 لطفا به‌شدت در وارد کردن آدرس ولت، مقدار ترون و روش کسر کارمزد دقت کنید. درصورت نهایی شدن تراکنش به هیچ‌وجه امکان بازگشت میسر نخواهد بود.\n"
                "🔹 کلیه تراکنش‌ها به طور کامل در دیتابیس ذخیره می‌شوند، لذا درصورت بروز خطا در هر یک از مراحل تراکنش میتوانید با پشتیبانی در ارتباط باشید.\n\n"
                "🔻 کلیک روی دکمه زیر و ثبت سفارش به منزله تایید قوانین ذکر شده می‌باشد.",
                reply_markup=markup
            )
            await query.message.delete()
            
    elif query.data == "accept_rules":
        user_data[query.message.chat.id] = {"status": "buying"}
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")]
            ])
        prompt_message = await query.message.reply_text(
            "لطفاً مقدار ترون درخواستی خود را وارد کنید. (حداقل 1 و حداکثر 1350)",
            reply_markup=markup
            )
        context.user_data[query.message.chat.id] = {
            'trx_prompt_message_id': prompt_message.message_id
            }
        await query.message.delete()

    elif query.data == "cancel":
        await query.message.delete()
        user_data[query.message.chat.id] = {"status": "idle"}
        await query.message.reply_text("✅ عملیات لغو شد. به منوی اصلی بازگشتید.")
        await start_handler(update, context)

    elif query.data == "request_acceptance":
        await query.message.reply_text("برای درخواست پذیرندگی، اطلاعات خود را ارسال کنید.")
        await query.message.delete()

    elif query.data == "contact_us":
        await query.message.reply_text("برای ارتباط با ما یا رهگیری تراکنش، با پشتیبانی تماس بگیرید.")
        await query.message.delete()

    elif query.data == 'check_membership':
        user_id = query.from_user.id
        if await check_membership(context.bot, user_id):
            await query.message.delete()
            await query.message.reply_text("عضویت شما تایید شد. اکنون می‌توانید از امکانات ربات استفاده کنید.")
            user_data[query.message.chat.id] = {"status": "idle"}
            await start_handler(update, context)
        else:
            await query.message.reply_text("لطفاً در تمام کانال‌های اسپانسر عضو شوید و دوباره تلاش کنید.")

    elif query.data == "user_info":
        user_id = query.from_user.id
        conn = sqlite3.connect(USERS_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT role, card_number FROM users WHERE user_id = ?", (user_id,))
        user_info = cursor.fetchone()
        conn.close()

        if user_info:
            role, card_number = user_info
            role_text = "عادی" if role == 1 else "پذیرنده" if role == 2 else "مدیر"
            response_text = (
                f"✅ اطلاعات کاربری شما در ترون استار:\n\n"
                f"شماره کاربری: {user_id}\n"
                f"نوع کاربر: {role_text}\n"
                f"شماره کارت: {card_number if card_number else 'ثبت نشده'}\n"
                )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("ویرایش شماره کارت 💳", callback_data="edit_card")],
                [InlineKeyboardButton("لیست تراکنش‌ها 🧾", callback_data="list_transactions")]
                ])
            
            await query.message.reply_text(response_text, reply_markup=markup)
        else:
            await query.message.reply_text("❌ اطلاعات کاربری پیدا نشد.")

    elif query.data == "list_transactions":
        await list_transactions_handler(update, context)
        await query.message.delete()
        
    elif query.data == "edit_card":
        await edit_card_handler(update, context)

    elif query.data.startswith("view_"):
        await view_transaction_handler(update, context)

    elif query.data == "prev_page":
        user_id = update.effective_chat.id
        context.user_data[f'page_{user_id}'] = max(0, context.user_data.get(f'page_{user_id}', 0) - 1)
        await list_transactions_handler(update, context)
        await query.message.delete()

    elif query.data == "next_page":
        user_id = update.effective_chat.id
        context.user_data[f'page_{user_id}'] = context.user_data.get(f'page_{user_id}', 0) + 1
        await list_transactions_handler(update, context)
        await query.message.delete()

    elif query.data == "fee_toman":
        trx_amount = user_data[query.message.chat.id]["trx_amount"]
        wallet_address = user_data[query.message.chat.id]["wallet"]
        fee_method = query.data

        invoice_number = generate_invoice_number()  # تولید شماره فاکتور
        fee_toman = int((trx_amount * 1.05 + 1.5) * get_trx_price())  # محاسبه مبلغ قابل پرداخت

        # ایجاد فاکتور
        payment_url, invoice_number = await create_invoice(query.message.chat_id, trx_amount, fee_method, wallet_address)
    
        if payment_url:
            user_data[query.message.chat_id] = {"status": "waiting_for_payment", "invoice": invoice_number}
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 پرداخت فاکتور", url=payment_url)],
                [InlineKeyboardButton("❌ لغو", callback_data="cancel_invoice")]
                ])
            
            message = await query.message.reply_text(
                f"✅ تراکنش شما با شماره {invoice_number} اطلاعات زیر در انتظار پرداخت فاکتور می‌باشد:\n\n"
                f"🔹 مقدار ترون: {trx_amount}\n"
                f"🔹 آدرس ولت: {wallet_address}\n"
                f"🔹 روش پرداخت کارمزد: فاکتور تومانی\n\n"
                f"💳 مبلغ قابل پرداخت: {format_price(fee_toman)} تومان\n\n"
                f"🔻 فاکتور تا ۱۵ دقیقه آینده منقضی خواهد شد، لطفاً سریع‌تر پرداخت خود را نهایی کنید.\n\n"
                f"⚠️ با دکمه زیر فاکتور خود را پرداخت کنید. پرداخت فقط با آی‌پی ایران امکان‌پذیر است. لطفاً فیلترشکن خود را خاموش کنید و از کارتی که به نام خودتان است استفاده کنید.",
                reply_markup=markup
                )
            await query.message.delete()
            update_message_chat_id(invoice_number, message.message_id)

        else:
            user_data[query.message.chat_id] = {"status": "idle"}
            await query.message.delete()
            await query.message.reply_text(
                f"❌ کاربر گرامی، فاکتور شما با شماره {invoice_number} به دلیل وجود خطا در درخواست به پذیرنده صادر نشد. لطفاً مجدداً تلاش کنید."
                )
            await start_handler(update, context)  # بازگشت به منوی اصلی


    elif query.data == "fee_trx":
        trx_amount = user_data[query.message.chat.id]["trx_amount"]
        wallet_address = user_data[query.message.chat.id]["wallet"]
        fee_method = query.data

        invoice_number = generate_invoice_number()  # تولید شماره فاکتور
        fee_toman = int(trx_amount * 1.05 * get_trx_price())  # محاسبه مبلغ به تومان
        received_trx = trx_amount - 1.5  # مقدار ترونی که کاربر دریافت می‌کند

        # ایجاد فاکتور
        payment_url, invoice_number = await create_invoice(query.message.chat_id, trx_amount, fee_method, wallet_address)

        if payment_url:
            # موفقیت در ایجاد فاکتور
            user_data[query.message.chat_id] = {"status": "waiting_for_payment", "invoice": invoice_number}

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 پرداخت فاکتور", url=payment_url)],
                [InlineKeyboardButton("❌ لغو", callback_data="cancel_invoice")]
            ])

            message = await query.message.reply_text(
                f"✅ تراکنش شما با شماره {invoice_number} اطلاعات زیر در انتظار پرداخت فاکتور می‌باشد:\n\n"
                f"🔹 مقدار ترون: {trx_amount}\n"
                f"🔹 آدرس ولت: {wallet_address}\n"
                f"🔹 روش پرداخت کارمزد: ترون\n\n"
                f"💳 مبلغ قابل پرداخت: {format_price(fee_toman)} تومان\n\n"
                f"🔴 در این روش، فی انتقال شبکه از ترون ارسال شده کسر خواهد شد. شما حدود {received_trx:.1f} ترون دریافت خواهید کرد.\n\n"
                f"🔻 فاکتور تا ۱۵ دقیقه آینده منقضی خواهد شد، لطفاً سریع‌تر پرداخت خود را نهایی کنید.\n\n"
                f"⚠️ با دکمه زیر فاکتور خود را پرداخت کنید. پرداخت فقط با آی‌پی ایران امکان‌پذیر است. لطفاً فیلترشکن خود را خاموش کنید و از کارتی که به نام خودتان است استفاده کنید.",
                reply_markup=markup
            )
            update_message_chat_id(invoice_number, message.message_id)
        else:
            user_data[query.message.chat_id] = {"status": "idle"}
            await query.message.delete()
            await query.message.reply_text(
                f"❌ کاربر گرامی، فاکتور شما با شماره {invoice_number} به دلیل وجود خطا در درخواست به پذیرنده صادر نشد. لطفاً مجدداً تلاش کنید."
            )
            await start_handler(update, context)  # بازگشت به منوی اصلی


    elif query.data == "cancel_invoice":
        invoice_number = user_data.get(query.message.chat.id, {}).get("invoice", "نامشخص")
        user_data[query.message.chat.id] = {"status": "idle"}
        update_invoice_status(invoice_number, "canceled")
        await query.message.delete()  # حذف پیام فاکتور
        await query.message.reply_text(f"❌ کاربر گرامی، سفارش شما با شماره {invoice_number} لغو شد.")
        await start_handler(update, context)  # بازگشت به منوی اصلی


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_status = context.user_data.get('status', 'idle')

    if user_status == 'edit_card':
        card_number = update.message.text.replace(" ", "")
        if not card_number.isdigit() or len(card_number) != 16:
            await update.message.reply_text("❌ شماره کارت نامعتبر است. لطفاً یک شماره کارت 16 رقمی وارد کنید.")
            return
        
        user_id = update.effective_user.id
        # به‌روزرسانی شماره کارت در دیتابیس
        conn = sqlite3.connect(USERS_DB)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET card_number = ? WHERE user_id = ?", (card_number, user_id))
        conn.commit()
        conn.close()
        
        del context.user_data['status']  # حذف وضعیت ویرایش
        await update.message.reply_text("✅ شماره کارت شما با موفقیت به‌روزرسانی شد.")
        await show_main_menu(update, context)

    elif user_status == 'card':
        await handle_card_number(update, context)
    elif user_status == "buying":
        try:
            trx_amount = float(update.message.text)
            if trx_amount < 1 or trx_amount > 1350:
                await update.message.reply_text("❌ مقدار واردشده خارج از محدودیت است. لطفاً عددی بین 1 تا 1350 وارد کنید.")
                return

            context.user_data[update.effective_chat.id] = {
                "status": "waiting_for_wallet",
                "trx_amount": trx_amount
            }
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="cancel")]
            ])
            # ذخیره پیام درخواست آدرس ولت
            prompt_message = await update.message.reply_text(
                "لطفاً آدرس ولت ارز ترون خود را ارسال کنید.",
                reply_markup=markup
            )
            context.user_data[update.effective_chat.id]['wallet_prompt_message_id'] = prompt_message.message_id

            # حذف پیام مربوط به درخواست مقدار ترون
            if 'trx_prompt_message_id' in context.user_data[update.effective_chat.id]:
                trx_prompt_message_id = context.user_data[update.effective_chat.id]['trx_prompt_message_id']
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=trx_prompt_message_id)
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")

            await update.message.delete()

        except ValueError:
            await update.message.reply_text("❌ لطفاً مقدار ترون را به‌صورت عدد وارد کنید.")

    elif user_status == "waiting_for_wallet":
        wallet_address = update.message.text
        if len(wallet_address) < 30 or not wallet_address.startswith("T"):
            await update.message.reply_text("❌ آدرس ولت نامعتبر است. لطفاً دوباره تلاش کنید.")
            return

        trx_amount = context.user_data[update.effective_chat.id]["trx_amount"]
        context.user_data[update.effective_chat.id] = {
            "status": "waiting_for_payment",
            "trx_amount": trx_amount,
            "wallet": wallet_address
        }

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("فاکتور تومانی", callback_data="fee_toman")],
            [InlineKeyboardButton("ترون", callback_data="fee_trx")]
        ])
        await update.message.delete()
        await update.message.reply_text(
            "لطفاً روش پرداخت کارمزد انتقال شبکه ترون را انتخاب کنید.",
            reply_markup=markup
        )

        if 'wallet_prompt_message_id' in context.user_data[update.effective_chat.id]:
            wallet_prompt_message_id = context.user_data[update.effective_chat.id]['wallet_prompt_message_id']
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=wallet_prompt_message_id)
            except Exception as e:
                logger.error(f"Error deleting message: {e}")


# ====== تنظیمات اصلی ======
def main():
    init_db()  # اطمینان از ایجاد دیتابیس فاکتورها
    init_user_db()  # ایجاد دیتابیس کاربران
    
    # تغییر در ایجاد application
    application = Application.builder().token(TOKEN).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(CallbackQueryHandler(navigation_handler, pattern="^(next_page|prev_page)$"))
    application.add_handler(CallbackQueryHandler(view_transaction_handler, pattern="^view_"))

    try:
        # اضافه کردن job queue با exception handling
        if application.job_queue:
            application.job_queue.run_repeating(monitor_invoices, interval=60, first=0)
    except Exception as e:
        logger.error(f"Error setting up job queue: {e}")
        print("Warning: Job queue could not be initialized. Invoice monitoring may not work properly.")

    print("ربات فعال شد!")
    application.run_polling()

if __name__ == "__main__":
    main()