"""
Telegram Bot Handlers - جميع معالجات البوت
تم نقلها من app.py
"""
import json
import time
import random
import requests
import hashlib
import uuid
from telebot import types
from extensions import (
    bot, db, user_states, verification_codes,
    ADMIN_ID, logger, BOT_ACTIVE, SITE_URL,
    EDFAPAY_MERCHANT_ID, EDFAPAY_PASSWORD
)

# استيراد firestore للـ SERVER_TIMESTAMP
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

# استيراد دوال Firebase
from firebase_utils import (
    get_balance, add_balance, deduct_balance,
    get_categories, get_products, get_product_by_id,
    get_charge_key, use_charge_key, create_charge_key,
    save_pending_payment, get_pending_payment,
    get_all_products_for_store, get_all_charge_keys
)

from utils import generate_code
import telebot

# استيراد نظام الإشعارات
try:
    from notifications import notify_new_charge, notify_owner
except ImportError:
    notify_new_charge = lambda *args, **kwargs: None
    notify_owner = lambda *args, **kwargs: None

# دالة توليد كود التحقق
def generate_verification_code():
    return str(random.randint(100000, 999999))

# ثوابت الدفع
EDFAPAY_API_URL = 'https://api.edfapay.com/payment/initiate'

# متغيرات للتخزين المؤقت
merchant_invoices = {}
pending_payments = {}
active_orders = {}
transactions = {}

# === دالة مساعدة لتسجيل الرسائل ===
def log_message(message, handler_name):
    print("="*50)
    print(f"📨 {handler_name}")
    print(f"👤 المستخدم: {message.from_user.id} - {message.from_user.first_name}")
    print(f"💬 النص: {message.text}")
    print("="*50)

# === دالة جلب صورة المستخدم ===
def get_user_profile_photo(user_id):
    """جلب صورة بروفايل المستخدم من تيليجرام"""
    try:
        photos = bot.get_user_profile_photos(int(user_id), limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            photo_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
            return photo_url
    except Exception as e:
        print(f"⚠️ خطأ في جلب صورة البروفايل: {e}")
    return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    log_message(message, "معالج /start")
    try:
        user_id = str(message.from_user.id)
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += ' ' + message.from_user.last_name
        username = message.from_user.username or ''
        
        # جلب صورة البروفايل من تيليجرام
        profile_photo = get_user_profile_photo(user_id)
        
        # حفظ معلومات المستخدم في Firebase
        if db:
            try:
                user_ref = db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if not user_doc.exists:
                    user_data = {
                        'telegram_id': user_id,
                        'name': user_name,
                        'username': username,
                        'balance': 0.0,
                        'telegram_started': True,  # المستخدم بدأ محادثة مع البوت
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'last_seen': firestore.SERVER_TIMESTAMP
                    }
                    if profile_photo:
                        user_data['profile_photo'] = profile_photo
                    user_ref.set(user_data)
                    print(f"✅ مستخدم جديد تم إنشاؤه")
                else:
                    update_data = {
                        'name': user_name,
                        'username': username,
                        'telegram_started': True,  # تحديث: المستخدم بدأ محادثة مع البوت
                        'last_seen': firestore.SERVER_TIMESTAMP
                    }
                    if profile_photo:
                        update_data['profile_photo'] = profile_photo
                    user_ref.update(update_data)
                    print(f"✅ مستخدم موجود تم تحديثه")
            except Exception as e:
                print(f"⚠️ خطأ في Firebase: {e}")
        
        # إنشاء أزرار Inline داخل الرسالة
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_shop = types.InlineKeyboardButton("🏪 افتح السوق", callback_data="open_shop")
        btn_myid = types.InlineKeyboardButton("🆔 معرفي", callback_data="my_id")
        markup.add(btn_shop, btn_myid)
        
        # إرسال الرسالة
        print(f"📤 إرسال رسالة الترحيب...")
        result = bot.send_message(
            message.chat.id,
            "🌟 *أهلاً بك في السوق الآمن!* 🛡️\n\n"
            "منصة آمنة للبيع والشراء مع نظام حماية الأموال ❄️\n\n"
            "📌 *اختر من الأزرار أدناه:*",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        print(f"✅ تم الإرسال! message_id: {result.message_id}")
        
    except Exception as e:
        print(f"❌ خطأ في send_welcome: {e}")
        import traceback
        traceback.print_exc()

# معالج أزرار Inline
@bot.callback_query_handler(func=lambda call: call.data in ["open_shop", "my_id"])
def handle_inline_buttons(call):
    try:
        if call.data == "open_shop":
            # إرسال زر برابط الموقع
            markup = types.InlineKeyboardMarkup()
            btn = types.InlineKeyboardButton("🛒 الدخول للسوق", url=SITE_URL)
            markup.add(btn)
            bot.send_message(
                call.message.chat.id,
                f"🏪 *اضغط الزر أدناه لفتح السوق:*\n\n"
                f"🔗 الرابط: {SITE_URL}",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        elif call.data == "my_id":
            bot.send_message(
                call.message.chat.id,
                f"🆔 *الآيدي الخاص بك:*\n\n`{call.from_user.id}`\n\nأرسل هذا الرقم للمالك ليضيفك كمشرف!",
                parse_mode="Markdown"
            )
        # إزالة علامة التحميل من الزر
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"❌ خطأ في inline button: {e}")
        bot.answer_callback_query(call.id, "حدث خطأ!")

@bot.message_handler(commands=['my_id'])
def my_id(message):
    log_message(message, "معالج /my_id")
    try:
        bot.reply_to(message, f"🆔 الآيدي الخاص بك: `{message.from_user.id}`\n\nأرسل هذا الرقم للمالك ليضيفك كمشرف!", parse_mode="Markdown")
        print(f"✅ تم إرسال الآيدي")
    except Exception as e:
        print(f"❌ خطأ: {e}")

# تخزين بيانات المنتج المؤقتة
temp_product_data = {}

# أمر إضافة منتج (فقط للمالك)
@bot.message_handler(commands=['add_product'])
def add_product_command(message):
    # التحقق من أن المستخدم هو المالك
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    # بدء عملية إضافة منتج جديد
    user_id = message.from_user.id
    temp_product_data[user_id] = {}
    
    msg = bot.reply_to(message, "📦 **إضافة منتج جديد**\n\n📝 أرسل اسم المنتج:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_product_name)

def process_product_name(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['item_name'] = message.text.strip()
    bot.reply_to(message, f"✅ تم إضافة الاسم: {message.text.strip()}")
    
    msg = bot.send_message(message.chat.id, "💰 أرسل سعر المنتج (بالريال):")
    bot.register_next_step_handler(msg, process_product_price)

def process_product_price(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    # التحقق من السعر
    try:
        price = float(message.text.strip())
        temp_product_data[user_id]['price'] = str(price)
        bot.reply_to(message, f"✅ تم إضافة السعر: {price} ريال")
        
        # إرسال أزرار الفئات
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
        markup.add(
            types.KeyboardButton("نتفلكس"),
            types.KeyboardButton("شاهد"),
            types.KeyboardButton("ديزني بلس"),
            types.KeyboardButton("اوسن بلس"),
            types.KeyboardButton("فديو بريميم"),
            types.KeyboardButton("اشتراكات أخرى")
        )
        
        msg = bot.send_message(message.chat.id, "🏷️ اختر فئة المنتج:", reply_markup=markup)
        bot.register_next_step_handler(msg, process_product_category)
        
    except ValueError:
        msg = bot.reply_to(message, "❌ السعر يجب أن يكون رقماً! أرسل السعر مرة أخرى:")
        bot.register_next_step_handler(msg, process_product_price)

def process_product_category(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
    
    valid_categories = ["نتفلكس", "شاهد", "ديزني بلس", "اوسن بلس", "فديو بريميم", "اشتراكات أخرى"]
    
    if message.text.strip() not in valid_categories:
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
        markup.add(
            types.KeyboardButton("نتفلكس"),
            types.KeyboardButton("شاهد"),
            types.KeyboardButton("ديزني بلس"),
            types.KeyboardButton("اوسن بلس"),
            types.KeyboardButton("فديو بريميم"),
            types.KeyboardButton("اشتراكات أخرى")
        )
        msg = bot.reply_to(message, "❌ فئة غير صحيحة! اختر من الأزرار:", reply_markup=markup)
        return bot.register_next_step_handler(msg, process_product_category)
    
    temp_product_data[user_id]['category'] = message.text.strip()
    bot.reply_to(message, f"✅ تم اختيار الفئة: {message.text.strip()}", reply_markup=types.ReplyKeyboardRemove())
    
    msg = bot.send_message(message.chat.id, "📝 أرسل تفاصيل المنتج (مثل: مدة الاشتراك، المميزات، إلخ):")
    bot.register_next_step_handler(msg, process_product_details)

def process_product_details(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['details'] = message.text.strip()
    bot.reply_to(message, "✅ تم إضافة التفاصيل")
    
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("تخطي"))
    
    msg = bot.send_message(message.chat.id, "🖼️ أرسل رابط صورة المنتج (أو اضغط تخطي):", reply_markup=markup)
    bot.register_next_step_handler(msg, process_product_image)

def process_product_image(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
    
    if message.text.strip() == "تخطي":
        temp_product_data[user_id]['image_url'] = "https://placehold.co/300x200/6c5ce7/ffffff?text=No+Image"
        bot.reply_to(message, "⏭️ تم تخطي الصورة", reply_markup=types.ReplyKeyboardRemove())
    else:
        temp_product_data[user_id]['image_url'] = message.text.strip()
        bot.reply_to(message, "✅ تم إضافة رابط الصورة", reply_markup=types.ReplyKeyboardRemove())
    
    msg = bot.send_message(message.chat.id, "🔐 أرسل البيانات المخفية (الايميل والباسورد مثلاً):")
    bot.register_next_step_handler(msg, process_product_hidden_data)

def process_product_hidden_data(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج")
    
    temp_product_data[user_id]['hidden_data'] = message.text.strip()
    bot.reply_to(message, "✅ تم إضافة البيانات المخفية")
    
    # سؤال عن نوع التسليم
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("⚡ تسليم فوري"),
        types.KeyboardButton("👨‍💼 تسليم يدوي")
    )
    
    msg = bot.send_message(
        message.chat.id, 
        "📦 اختر نوع التسليم:\n\n"
        "⚡ **تسليم فوري**: يتم إرسال البيانات تلقائياً للمشتري\n"
        "👨‍💼 **تسليم يدوي**: يتم إشعار الأدمن لتنفيذ الطلب",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, process_product_delivery_type)

def process_product_delivery_type(message):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        temp_product_data.pop(user_id, None)
        return bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
    
    if message.text == "⚡ تسليم فوري":
        temp_product_data[user_id]['delivery_type'] = 'instant'
        delivery_display = "⚡ تسليم فوري"
    elif message.text == "👨‍💼 تسليم يدوي":
        temp_product_data[user_id]['delivery_type'] = 'manual'
        delivery_display = "👨‍💼 تسليم يدوي"
    else:
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
        markup.add(
            types.KeyboardButton("⚡ تسليم فوري"),
            types.KeyboardButton("👨‍💼 تسليم يدوي")
        )
        msg = bot.reply_to(message, "❌ اختيار غير صحيح! اختر من الأزرار:", reply_markup=markup)
        return bot.register_next_step_handler(msg, process_product_delivery_type)
    
    bot.reply_to(message, f"✅ نوع التسليم: {delivery_display}", reply_markup=types.ReplyKeyboardRemove())
    
    # عرض ملخص المنتج
    product = temp_product_data[user_id]
    summary = (
        "📦 **ملخص المنتج:**\n\n"
        f"📝 الاسم: {product['item_name']}\n"
        f"💰 السعر: {product['price']} ريال\n"
        f"🏷️ الفئة: {product['category']}\n"
        f"📋 التفاصيل: {product['details']}\n"
        f"🖼️ الصورة: {product['image_url']}\n"
        f"🔐 البيانات: {product['hidden_data']}\n"
        f"📦 التسليم: {delivery_display}\n\n"
        "هل تريد إضافة هذا المنتج؟"
    )
    
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("✅ موافق"),
        types.KeyboardButton("❌ إلغاء")
    )
    
    msg = bot.send_message(message.chat.id, summary, parse_mode="Markdown", reply_markup=markup)
    bot.register_next_step_handler(msg, confirm_add_product)

def confirm_add_product(message):
    user_id = message.from_user.id
    
    if message.text == "✅ موافق":
        product = temp_product_data.get(user_id)
        
        if product:
            # إضافة المنتج
            product_id = str(uuid.uuid4())  # رقم فريد لا يتكرر
            delivery_type = product.get('delivery_type', 'instant')
            item = {
                'id': product_id,
                'item_name': product['item_name'],
                'price': str(product['price']),
                'seller_id': str(ADMIN_ID),
                'seller_name': 'المالك',
                'hidden_data': product['hidden_data'],
                'category': product['category'],
                'details': product['details'],
                'image_url': product['image_url'],
                'delivery_type': delivery_type,
                'sold': False
            }
            
            # حفظ في Firebase أولاً
            try:
                db.collection('products').document(product_id).set({
                    'item_name': item['item_name'],
                    'price': float(product['price']),
                    'seller_id': str(ADMIN_ID),
                    'seller_name': 'المالك',
                    'hidden_data': item['hidden_data'],
                    'category': item['category'],
                    'details': item['details'],
                    'image_url': item['image_url'],
                    'delivery_type': delivery_type,
                    'sold': False,
                    'created_at': firestore.SERVER_TIMESTAMP
                })
                print(f"✅ تم حفظ المنتج {product_id} في Firebase")
            except Exception as e:
                print(f"❌ خطأ في حفظ المنتج في Firebase: {e}")
            
            # جلب عدد المنتجات من Firebase
            products_count = len(get_all_products_for_store())
            
            delivery_display = "⚡ فوري" if delivery_type == 'instant' else "👨‍💼 يدوي"
            bot.reply_to(message,
                         f"✅ **تم إضافة المنتج بنجاح!**\n\n"
                         f"📦 المنتج: {product['item_name']}\n"
                         f"💰 السعر: {product['price']} ريال\n"
                         f"🏷️ الفئة: {product['category']}\n"
                         f"📦 التسليم: {delivery_display}\n"
                         f"📊 إجمالي المنتجات: {products_count}",
                         parse_mode="Markdown",
                         reply_markup=types.ReplyKeyboardRemove())
        
        # حذف البيانات المؤقتة
        temp_product_data.pop(user_id, None)
    else:
        bot.reply_to(message, "❌ تم إلغاء إضافة المنتج", reply_markup=types.ReplyKeyboardRemove())
        temp_product_data.pop(user_id, None)

@bot.message_handler(commands=['code'])
def get_verification_code(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    if message.from_user.last_name:
        user_name += ' ' + message.from_user.last_name
    
    # توليد كود تحقق
    code = generate_verification_code(user_id, user_name)
    
    bot.send_message(message.chat.id,
                     f"🔐 **كود التحقق الخاص بك:**\n\n"
                     f"`{code}`\n\n"
                     f"⏱️ **صالح لمدة 10 دقائق**\n\n"
                     f"💡 **خطوات الدخول:**\n"
                     f"1️⃣ افتح الموقع في المتصفح\n"
                     f"2️⃣ اضغط على زر 'حسابي'\n"
                     f"3️⃣ أدخل الآيدي الخاص بك: `{user_id}`\n"
                     f"4️⃣ أدخل الكود أعلاه\n\n"
                     f"⚠️ لا تشارك هذا الكود مع أحد!",
                     parse_mode="Markdown")

# أمر خاص بالآدمن لشحن رصيد المستخدمين
# طريقة الاستخدام: /add ID AMOUNT
# مثال: /add 123456789 50
@bot.message_handler(commands=['add'])
def add_funds(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمشرف فقط.")
    
    try:
        parts = message.text.split()
        target_id = parts[1]
        amount = float(parts[2])
        add_balance(target_id, amount)
        
        # تسجيل في سجل الشحنات
        try:
            import time
            from datetime import datetime
            db.collection('charge_history').add({
                'user_id': str(target_id),
                'amount': amount,
                'method': 'admin',
                'order_id': '',
                'timestamp': time.time(),
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'type': 'admin_charge'
            })
        except:
            pass
        
        bot.reply_to(message, f"✅ تم إضافة {amount} ريال للمستخدم {target_id}")
        bot.send_message(target_id, f"🎉 تم شحن رصيدك بمبلغ {amount} ريال!")
    except:
        bot.reply_to(message, "خطأ! الاستخدام: /add ID AMOUNT")

# أمر تسجيل/التحقق من Callback URL في EdfaPay
# الاستخدام: /edfapay (للتحقق) أو /edfapay register (للتسجيل)
@bot.message_handler(commands=['edfapay'])
def edfapay_settings(message):
    """إدارة إعدادات EdfaPay"""
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    try:
        parts = message.text.split()
        action = parts[1] if len(parts) > 1 else "check"
        
        if action == "register":
            # تسجيل الـ callback URL
            bot.reply_to(message, "⏳ جاري تسجيل Callback URL في EdfaPay...")
            
            callback_url = f"{SITE_URL}/payment/edfapay_webhook"
            
            response = requests.post(
                "https://api.edfapay.com/payment/merchants/callback-url",
                json={
                    "action": "post",
                    "id": EDFAPAY_MERCHANT_ID,
                    "url": callback_url
                },
                timeout=30
            )
            
            if response.status_code == 200:
                bot.send_message(
                    message.chat.id,
                    f"✅ *تم تسجيل Callback URL بنجاح!*\n\n"
                    f"🔗 URL: `{callback_url}`\n\n"
                    f"📡 Response: `{response.text[:200]}`",
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(
                    message.chat.id,
                    f"❌ *فشل تسجيل Callback URL*\n\n"
                    f"📡 Status: {response.status_code}\n"
                    f"📡 Response: `{response.text[:200]}`",
                    parse_mode="Markdown"
                )
        else:
            # التحقق من الـ callback URL المسجل
            bot.reply_to(message, "⏳ جاري التحقق من Callback URL...")
            
            response = requests.post(
                "https://api.edfapay.com/payment/merchants/callback-url",
                json={
                    "action": "get",
                    "id": EDFAPAY_MERCHANT_ID
                },
                timeout=30
            )
            
            # تنظيف النص من الرموز الخاصة
            response_text = response.text[:300].replace('`', "'").replace('_', '-').replace('*', '')
            
            bot.send_message(
                message.chat.id,
                f"📡 حالة EdfaPay Callback\n\n"
                f"🔑 Merchant ID: {EDFAPAY_MERCHANT_ID}\n"
                f"🌐 SITE_URL: {SITE_URL}\n\n"
                f"📡 Response ({response.status_code}):\n{response_text}\n\n"
                f"💡 للتسجيل أرسل: /edfapay register"
            )
            
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {e}")

# أمر توليد مفاتيح الشحن
# الاستخدام: /توليد AMOUNT [COUNT]
# مثال: /توليد 50 10  (توليد 10 مفاتيح بقيمة 50 ريال لكل منها)
@bot.message_handler(commands=['توليد'])
def generate_keys(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    try:
        parts = message.text.split()
        amount = float(parts[1])
        count = int(parts[2]) if len(parts) > 2 else 1
        
        # التحقق من الحدود
        if count > 100:
            return bot.reply_to(message, "❌ الحد الأقصى 100 مفتاح في المرة الواحدة!")
        
        if amount <= 0:
            return bot.reply_to(message, "❌ المبلغ يجب أن يكون أكبر من صفر!")
        
        # توليد المفاتيح
        generated_keys = []
        for i in range(count):
            # توليد مفتاح عشوائي
            key_code = f"KEY-{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"
            
            # حفظ في Firebase مباشرة
            try:
                create_charge_key(key_code, amount)
            except Exception as e:
                print(f"⚠️ خطأ في حفظ المفتاح في Firebase: {e}")
            
            generated_keys.append(key_code)
        
        # إرسال المفاتيح
        if count == 1:
            response = (
                f"🎁 **تم توليد المفتاح بنجاح!**\n\n"
                f"💰 القيمة: {amount} ريال\n"
                f"🔑 المفتاح:\n"
                f"`{generated_keys[0]}`\n\n"
                f"📝 يمكن للمستخدم شحنه بإرسال: /شحن {generated_keys[0]}"
            )
        else:
            keys_text = "\n".join([f"`{key}`" for key in generated_keys])
            response = (
                f"🎁 **تم توليد {count} مفتاح بنجاح!**\n\n"
                f"💰 قيمة كل مفتاح: {amount} ريال\n"
                f"💵 المجموع الكلي: {amount * count} ريال\n\n"
                f"🔑 المفاتيح:\n{keys_text}\n\n"
                f"📝 الاستخدام: /شحن [المفتاح]"
            )
        
        bot.reply_to(message, response, parse_mode="Markdown")
        
    except IndexError:
        bot.reply_to(message, 
                     "❌ **خطأ في الاستخدام!**\n\n"
                     "📝 الصيغة الصحيحة:\n"
                     "`/توليد [المبلغ] [العدد]`\n\n"
                     "**أمثلة:**\n"
                     "• `/توليد 50` - مفتاح واحد بقيمة 50 ريال\n"
                     "• `/توليد 100 5` - 5 مفاتيح بقيمة 100 ريال لكل منها\n"
                     "• `/توليد 25 10` - 10 مفاتيح بقيمة 25 ريال لكل منها",
                     parse_mode="Markdown")
    except ValueError:
        bot.reply_to(message, "❌ الرجاء إدخال أرقام صحيحة!")

# أمر شحن الرصيد (يفتح خيارات الشحن)
@bot.message_handler(commands=['شحن'])
def recharge_balance(message):
    """أمر شحن الرصيد - يعرض خيارات الشحن"""
    try:
        user_id = str(message.from_user.id)
        
        # إنشاء أزرار خيارات الشحن
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_payment = types.InlineKeyboardButton("💳 شحن إلكتروني", callback_data="recharge_payment")
        btn_code = types.InlineKeyboardButton("🔑 شحن بكود", callback_data="recharge_code")
        markup.add(btn_payment)
        markup.add(btn_code)
        
        bot.send_message(
            message.chat.id,
            "💰 *شحن الرصيد*\n\n"
            "اختر طريقة الشحن:\n\n"
            "💳 *شحن إلكتروني* - الدفع عبر بوابة الدفع\n"
            "🔑 *شحن بكود* - إذا لديك كود شحن",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {str(e)}")

# معالج زر شحن إلكتروني
@bot.callback_query_handler(func=lambda call: call.data == "recharge_payment")
def handle_recharge_payment(call):
    """طلب إدخال مبلغ الشحن"""
    try:
        user_id = str(call.from_user.id)
        
        # التحقق من إعدادات بوابة الدفع EdfaPay
        if not EDFAPAY_MERCHANT_ID or not EDFAPAY_PASSWORD:
            bot.answer_callback_query(call.id, "❌ بوابة الدفع غير مفعلة حالياً")
            return bot.send_message(
                call.message.chat.id,
                "❌ *عذراً، بوابة الدفع غير مفعلة حالياً*\n\n"
                "يمكنك استخدام أكواد الشحن بدلاً من ذلك.",
                parse_mode="Markdown"
            )
        
        # تعيين حالة المستخدم لانتظار المبلغ
        user_states[user_id] = {
            'state': 'waiting_recharge_amount',
            'created_at': time.time()
        }
        
        bot.answer_callback_query(call.id)
        
        # إنشاء زر إلغاء
        markup = types.InlineKeyboardMarkup()
        btn_cancel = types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_recharge")
        markup.add(btn_cancel)
        
        bot.send_message(
            call.message.chat.id,
            "💳 *شحن رصيد إلكتروني*\n\n"
            "💵 أدخل المبلغ الذي تريد شحنه بالريال:\n\n"
            "📌 *مثال:* `50` أو `100`\n\n"
            "⚠️ الحد الأدنى: 10 ريال\n"
            "⚠️ الحد الأقصى: 1000 ريال",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "حدث خطأ!")
        print(f"❌ خطأ في handle_recharge_payment: {e}")

# معالج زر شحن بكود
@bot.callback_query_handler(func=lambda call: call.data == "recharge_code")
def handle_recharge_code(call):
    """طلب إدخال كود الشحن"""
    try:
        user_id = str(call.from_user.id)
        
        # تعيين حالة المستخدم لانتظار الكود
        user_states[user_id] = {
            'state': 'waiting_recharge_code',
            'created_at': time.time()
        }
        
        bot.answer_callback_query(call.id)
        
        # إنشاء زر إلغاء
        markup = types.InlineKeyboardMarkup()
        btn_cancel = types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_recharge")
        markup.add(btn_cancel)
        
        bot.send_message(
            call.message.chat.id,
            "🔑 *شحن بكود*\n\n"
            "📝 أرسل كود الشحن الخاص بك:\n\n"
            "📌 *مثال:* `KEY-XXXXX-XXXXX`",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "حدث خطأ!")
        print(f"❌ خطأ في handle_recharge_code: {e}")

# معالج زر إلغاء الشحن
@bot.callback_query_handler(func=lambda call: call.data == "cancel_recharge")
def handle_cancel_recharge(call):
    """إلغاء عملية الشحن"""
    try:
        user_id = str(call.from_user.id)
        
        # إزالة حالة المستخدم
        if user_id in user_states:
            del user_states[user_id]
        
        bot.answer_callback_query(call.id, "تم الإلغاء")
        bot.send_message(
            call.message.chat.id,
            "❌ تم إلغاء عملية الشحن.\n\n"
            "يمكنك البدء من جديد بإرسال /شحن",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "حدث خطأ!")

# دالة إنشاء فاتورة دفع من EdfaPay
def create_edfapay_invoice(user_id, amount, user_name):
    """إنشاء فاتورة دفع في EdfaPay"""
    try:
        # توليد معرف فريد للطلب
        order_id = f"TR{user_id}{int(time.time())}"
        order_description = f"Recharge {amount} SAR"
        
        # إنشاء الـ Hash
        # Formula: hash = SHA1(MD5(UPPERCASE(order_id + order_amount + order_currency + order_description + merchant_password)))
        to_hash = f"{order_id}{amount}SAR{order_description}{EDFAPAY_PASSWORD}".upper()
        md5_hash = hashlib.md5(to_hash.encode()).hexdigest()
        final_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
        
        # جلب IP العميل (نستخدم قيمة افتراضية)
        payer_ip = "176.44.76.222"
        
        # بيانات الطلب لـ EdfaPay API (multipart/form-data)
        payload = {
            'action': 'SALE',
            'edfa_merchant_id': EDFAPAY_MERCHANT_ID,
            'order_id': order_id,
            'order_amount': str(amount),
            'order_currency': 'SAR',
            'order_description': order_description,
            'req_token': 'N',
            'payer_first_name': user_name or 'Customer',
            'payer_last_name': 'User',
            'payer_address': 'Riyadh',
            'payer_country': 'SA',
            'payer_city': 'Riyadh',
            'payer_zip': '12221',
            'payer_email': f'user{user_id}@telegram.com',
            'payer_phone': '966500000000',
            'payer_ip': payer_ip,
            'term_url_3ds': f"{SITE_URL}/payment/success?order_id={order_id}",
            'auth': 'N',
            'recurring_init': 'N',
            'hash': final_hash
        }
        
        print(f"📤 EdfaPay Request: {payload}")
        
        # إرسال الطلب (multipart/form-data)
        # استخدام API الإنتاج
        api_url = "https://api.edfapay.com/payment/initiate"
        
        response = requests.post(api_url, data=payload, timeout=30)
        print(f"📤 EdfaPay Response Status: {response.status_code}")
        print(f"📤 EdfaPay Response: {response.text[:500]}")
        
        result = response.json()
        
        # التحقق من النجاح
        if response.status_code == 200 and result.get('redirect_url'):
            payment_url = result.get('redirect_url')
            
            # حفظ الطلب المعلق
            pending_payments[order_id] = {
                'user_id': user_id,
                'amount': amount,
                'order_id': order_id,
                'status': 'pending',
                'created_at': time.time()
            }
            
            # حفظ في Firebase
            try:
                db.collection('pending_payments').document(order_id).set({
                    'user_id': user_id,
                    'amount': amount,
                    'order_id': order_id,
                    'status': 'pending',
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"⚠️ خطأ في حفظ الطلب في Firebase: {e}")
            
            return {
                'success': True,
                'payment_url': payment_url,
                'invoice_id': order_id
            }
        else:
            error_msg = result.get('message') or result.get('error') or result.get('errors') or result
            print(f"❌ EdfaPay Error: {error_msg}")
            return {
                'success': False,
                'error': str(error_msg)
            }
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'انتهت مهلة الاتصال'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'خطأ في الاتصال: {str(e)}'}
    except Exception as e:
        print(f"❌ Exception in create_edfapay_invoice: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

# معالج الرسائل النصية (للمبالغ والأكواد)
@bot.message_handler(func=lambda message: str(message.from_user.id) in user_states)
def handle_user_state_message(message):
    """معالج رسائل المستخدمين حسب حالتهم"""
    try:
        user_id = str(message.from_user.id)
        state_data = user_states.get(user_id)
        
        if not state_data:
            return
        
        # التحقق من صلاحية الحالة (10 دقائق)
        if time.time() - state_data.get('created_at', 0) > 600:
            del user_states[user_id]
            return bot.reply_to(message, "⏱ انتهت صلاحية العملية. أرسل /شحن للبدء من جديد")
        
        state = state_data.get('state')
        
        # === حالة انتظار مبلغ الشحن ===
        if state == 'waiting_recharge_amount':
            text = message.text.strip()
            
            # التحقق من أن المدخل رقم
            try:
                amount = float(text)
            except ValueError:
                return bot.reply_to(message, "❌ الرجاء إدخال رقم صحيح فقط (مثال: 50)")
            
            # التحقق من الحدود
            if amount < 10:
                return bot.reply_to(message, "❌ الحد الأدنى للشحن هو 10 ريال")
            if amount > 1000:
                return bot.reply_to(message, "❌ الحد الأقصى للشحن هو 1000 ريال")
            
            # إزالة حالة المستخدم
            del user_states[user_id]
            
            # إرسال رسالة انتظار
            wait_msg = bot.reply_to(message, "⏳ جاري إنشاء رابط الدفع...")
            
            # إنشاء الفاتورة
            user_name = message.from_user.first_name
            result = create_edfapay_invoice(user_id, amount, user_name)
            
            if result['success']:
                # إنشاء زر للدفع
                markup = types.InlineKeyboardMarkup()
                btn_pay = types.InlineKeyboardButton("💳 ادفع الآن", url=result['payment_url'])
                markup.add(btn_pay)
                
                bot.edit_message_text(
                    f"✅ *تم إنشاء طلب الشحن!*\n\n"
                    f"💰 المبلغ: {amount} ريال\n"
                    f"📋 رقم الطلب: `{result['invoice_id']}`\n\n"
                    f"👇 اضغط الزر أدناه للدفع:\n\n"
                    f"⚠️ بعد الدفع سيتم إضافة الرصيد تلقائياً",
                    chat_id=wait_msg.chat.id,
                    message_id=wait_msg.message_id,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                
                # إشعار المالك
                try:
                    bot.send_message(ADMIN_ID,
                        f"🔔 *طلب شحن جديد*\n\n"
                        f"👤 المستخدم: {user_name}\n"
                        f"🆔 الآيدي: {user_id}\n"
                        f"💰 المبلغ: {amount} ريال\n"
                        f"📋 رقم الطلب: `{result['invoice_id']}`",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                bot.edit_message_text(
                    f"❌ *فشل إنشاء طلب الدفع*\n\n"
                    f"السبب: {result['error']}\n\n"
                    f"حاول مرة أخرى لاحقاً أو تواصل مع الدعم",
                    chat_id=wait_msg.chat.id,
                    message_id=wait_msg.message_id,
                    parse_mode="Markdown"
                )
        
        # === حالة انتظار كود الشحن ===
        elif state == 'waiting_recharge_code':
            key_code = message.text.strip()
            user_name = message.from_user.first_name
            
            # إزالة حالة المستخدم
            del user_states[user_id]
            
            # التحقق من وجود المفتاح
            # جلب بيانات المفتاح من Firebase
            key_data = get_charge_key(key_code)
            
            if not key_data:
                return bot.reply_to(message, "❌ المفتاح غير صحيح أو منتهي الصلاحية!")
            
            # التحقق من استخدام المفتاح
            if key_data.get('used', False):
                return bot.reply_to(message, 
                    f"❌ هذا المفتاح تم استخدامه بالفعل!\n\n"
                    f"👤 استخدمه: {key_data.get('used_by', 'مستخدم')}")
            
            # شحن الرصيد
            amount = key_data.get('amount', 0)
            add_balance(user_id, amount)
            
            # ✅ تسجيل الشحنة في charge_history للتجميد
            try:
                db.collection('charge_history').add({
                    'user_id': str(user_id),
                    'amount': float(amount),
                    'method': 'telegram_key',
                    'key_code': key_code,
                    'timestamp': firestore.SERVER_TIMESTAMP
                })
                print(f"✅ تم تسجيل شحنة التليجرام في charge_history: {amount} ريال للمستخدم {user_id}")
                
                # إشعار المالك بالشحن
                notify_new_charge(user_id, amount, method='telegram_key', username=user_name)
            except Exception as e:
                print(f"⚠️ خطأ في تسجيل charge_history: {e}")
            
            # تحديث حالة المفتاح في Firebase
            use_charge_key(key_code, user_name)
            
            # إرسال رسالة نجاح
            bot.reply_to(message,
                f"✅ *تم شحن رصيدك بنجاح!*\n\n"
                f"💰 المبلغ المضاف: {amount} ريال\n"
                f"💵 رصيدك الحالي: {get_balance(user_id)} ريال\n\n"
                f"⏳ *ملاحظة:* المبلغ سيكون متاحاً للسحب العادي بعد 72 ساعة.\n"
                f"⚡ يمكنك السحب الفوري الآن برسوم 8%.\n\n"
                f"🎉 استمتع بالتسوق!",
                parse_mode="Markdown"
            )
            
            # إشعار المالك
            try:
                bot.send_message(ADMIN_ID,
                    f"🔔 *تم استخدام مفتاح شحن*\n\n"
                    f"👤 المستخدم: {user_name}\n"
                    f"🆔 الآيدي: {user_id}\n"
                    f"💰 المبلغ: {amount} ريال\n"
                    f"🔑 المفتاح: `{key_code}`",
                    parse_mode="Markdown"
                )
            except:
                pass
        
        # === حالة انتظار مبلغ الفاتورة ===
        elif state == 'waiting_invoice_amount':
            text = message.text.strip()
            merchant_name = state_data.get('merchant_name', message.from_user.first_name)
            
            # التحقق من أن المدخل رقم
            try:
                amount = float(text)
            except ValueError:
                return bot.reply_to(message, "❌ الرجاء إدخال رقم صحيح فقط (مثال: 100)")
            
            # التحقق من الحدود
            if amount < 1:
                return bot.reply_to(message, "❌ الحد الأدنى للفاتورة هو 1 ريال")
            if amount > 10000:
                return bot.reply_to(message, "❌ الحد الأقصى للفاتورة هو 10,000 ريال")
            
            # إزالة حالة المستخدم
            del user_states[user_id]
            
            # إنشاء معرف فريد للفاتورة
            invoice_id = generate_invoice_id()
            invoice_url = f"{SITE_URL}/invoice/{invoice_id}"
            
            # حفظ الفاتورة المعلقة (بدون رقم هاتف بعد)
            merchant_invoices[invoice_id] = {
                'invoice_id': invoice_id,
                'merchant_id': user_id,
                'merchant_name': merchant_name,
                'amount': amount,
                'customer_phone': None,
                'status': 'waiting_payment',
                'created_at': time.time()
            }
            
            # حفظ في Firebase
            try:
                db.collection('merchant_invoices').document(invoice_id).set({
                    'invoice_id': invoice_id,
                    'merchant_id': user_id,
                    'merchant_name': merchant_name,
                    'amount': amount,
                    'customer_phone': None,
                    'status': 'waiting_payment',
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"⚠️ خطأ في حفظ الفاتورة: {e}")
            
            # إرسال رابط الفاتورة للتاجر
            bot.send_message(
                message.chat.id,
                f"✅ *تم إنشاء الفاتورة بنجاح!*\n\n"
                f"💰 المبلغ: {amount} ريال\n"
                f"🆔 رقم الفاتورة: `{invoice_id}`\n\n"
                f"🔗 *رابط الفاتورة:*\n`{invoice_url}`\n\n"
                f"📤 أرسل هذا الرابط للعميل للدفع",
                parse_mode="Markdown"
            )
                
    except Exception as e:
        print(f"❌ خطأ في handle_user_state_message: {e}")

# أمر عرض المفاتيح النشطة (للمالك فقط)
@bot.message_handler(commands=['المفاتيح'])
def list_keys(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ هذا الأمر للمالك فقط!")
    
    # جلب المفاتيح من Firebase
    all_keys = get_all_charge_keys()
    active_keys = {k: v for k, v in all_keys.items() if not v.get('used', False)}
    used_count = len(all_keys) - len(active_keys)
    
    if not all_keys:
        return bot.reply_to(message, "📭 لا توجد مفاتيح محفوظة!")
    
    response = f"📊 **إحصائيات المفاتيح**\n\n"
    response += f"✅ مفاتيح نشطة: {len(active_keys)}\n"
    response += f"🚫 مفاتيح مستخدمة: {used_count}\n"
    response += f"📈 الإجمالي: {len(all_keys)}\n\n"
    
    if active_keys:
        total_value = sum([v.get('amount', 0) for v in active_keys.values()])
        response += f"💰 القيمة الإجمالية للمفاتيح النشطة: {total_value} ريال"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['web'])
def open_web_app(message):
    bot.send_message(message.chat.id, 
                     f"🏪 **مرحباً بك في السوق!**\n\n"
                     f"افتح الرابط التالي في متصفحك لتصفح المنتجات:\n\n"
                     f"🔗 {SITE_URL}\n\n"
                     f"💡 **نصيحة:** انسخ الرابط وافتحه في متصفح خارجي (Chrome/Safari) "
                     f"للحصول على أفضل تجربة!",
                     parse_mode="Markdown")

# ============ نظام الفواتير للتجار ============

@bot.message_handler(commands=['فاتورة'])
def create_invoice_command(message):
    """أمر إنشاء فاتورة للعميل"""
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    
    # تعيين حالة انتظار إدخال مبلغ الفاتورة
    user_states[user_id] = {
        'state': 'waiting_invoice_amount',
        'created_at': time.time(),
        'merchant_name': user_name
    }
    
    # إنشاء زر إلغاء
    markup = types.InlineKeyboardMarkup()
    btn_cancel = types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_invoice")
    markup.add(btn_cancel)
    
    bot.send_message(
        message.chat.id,
        "🧾 *إنشاء فاتورة جديدة*\n\n"
        "💰 أدخل مبلغ الفاتورة بالريال:\n\n"
        "_مثال: 100_",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "cancel_invoice")
def handle_cancel_invoice(call):
    """إلغاء إنشاء الفاتورة"""
    user_id = str(call.from_user.id)
    
    if user_id in user_states:
        del user_states[user_id]
    
    bot.answer_callback_query(call.id, "تم الإلغاء")
    bot.edit_message_text(
        "❌ تم إلغاء إنشاء الفاتورة.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

def generate_invoice_id():
    """توليد معرف قصير وفريد للفاتورة"""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choice(chars) for _ in range(6))

def create_customer_invoice(merchant_id, merchant_name, amount, customer_phone, original_invoice_id=None):
    """إنشاء فاتورة دفع للعميل وإرسالها لـ EdfaPay"""
    try:
        # استخدام معرف الفاتورة الأصلي أو توليد جديد
        invoice_id = original_invoice_id or f"INV{generate_invoice_id()}"
        order_id = f"{invoice_id}{int(time.time())}"
        order_description = f"Invoice {invoice_id} - {amount} SAR"
        
        # إنشاء الـ Hash
        to_hash = f"{order_id}{amount}SAR{order_description}{EDFAPAY_PASSWORD}".upper()
        md5_hash = hashlib.md5(to_hash.encode()).hexdigest()
        final_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
        
        # تنظيف رقم الهاتف (الرقم يأتي كاملاً مع رمز الدولة من الصفحة)
        phone = customer_phone.strip()
        # إزالة + إن وجدت
        phone = phone.replace('+', '')
        # إزالة المسافات
        phone = phone.replace(' ', '')
        # إذا بدأ بصفر، أضف 966 (للتوافق مع الأرقام القديمة)
        if phone.startswith('0'):
            phone = '966' + phone[1:]
        
        # بيانات الطلب
        payload = {
            'action': 'SALE',
            'edfa_merchant_id': EDFAPAY_MERCHANT_ID,
            'order_id': order_id,
            'order_amount': str(amount),
            'order_currency': 'SAR',
            'order_description': order_description,
            'req_token': 'N',
            'payer_first_name': 'Customer',
            'payer_last_name': 'User',
            'payer_address': 'Saudi Arabia',
            'payer_country': 'SA',
            'payer_city': 'Riyadh',
            'payer_zip': '12221',
            'payer_email': f'customer{int(time.time())}@invoice.com',
            'payer_phone': phone,
            'payer_ip': '176.44.76.222',
            'term_url_3ds': f"{SITE_URL}/payment/success?order_id={order_id}&invoice={invoice_id}",
            'auth': 'N',
            'recurring_init': 'N',
            'hash': final_hash
        }
        
        print(f"📤 EdfaPay Invoice Request: {payload}")
        
        response = requests.post(EDFAPAY_API_URL, data=payload, timeout=30)
        print(f"📤 EdfaPay Response: {response.status_code} - {response.text[:500]}")
        
        result = response.json()
        
        if response.status_code == 200 and result.get('redirect_url'):
            payment_url = result.get('redirect_url')
            
            # حفظ الفاتورة في الذاكرة (صلاحية ساعة واحدة)
            expires_at = time.time() + 3600  # ساعة واحدة
            merchant_invoices[invoice_id] = {
                'invoice_id': invoice_id,
                'order_id': order_id,
                'merchant_id': merchant_id,
                'merchant_name': merchant_name,
                'amount': amount,
                'customer_phone': phone,
                'status': 'pending',
                'created_at': time.time(),
                'expires_at': expires_at
            }
            
            # حفظ الطلب المعلق (لربطه بالـ webhook)
            pending_payments[order_id] = {
                'user_id': merchant_id,  # سيتم إضافة الرصيد للتاجر
                'amount': amount,
                'order_id': order_id,
                'invoice_id': invoice_id,
                'is_merchant_invoice': True,  # علامة أنها فاتورة تاجر
                'status': 'pending',
                'created_at': time.time()
            }
            
            # حفظ في Firebase
            try:
                db.collection('merchant_invoices').document(invoice_id).set({
                    'invoice_id': invoice_id,
                    'order_id': order_id,
                    'merchant_id': merchant_id,
                    'merchant_name': merchant_name,
                    'amount': amount,
                    'customer_phone': phone,
                    'status': 'pending',
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'expires_at': expires_at
                })
                
                db.collection('pending_payments').document(order_id).set({
                    'user_id': merchant_id,
                    'amount': amount,
                    'order_id': order_id,
                    'invoice_id': invoice_id,
                    'is_merchant_invoice': True,
                    'status': 'pending',
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"⚠️ خطأ في حفظ الفاتورة في Firebase: {e}")
            
            return {
                'success': True,
                'payment_url': payment_url,
                'invoice_id': invoice_id,
                'order_id': order_id
            }
        else:
            error_msg = result.get('message') or result.get('error') or str(result)
            return {'success': False, 'error': error_msg}
            
    except Exception as e:
        print(f"❌ Exception in create_customer_invoice: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

# زر استلام الطلب من قبل المشرف (النظام القديم - للطلبات في الذاكرة)
@bot.callback_query_handler(func=lambda call: call.data.startswith('claim_') and not call.data.startswith('claim_order_'))
def claim_order(call):
    order_id = call.data.replace('claim_', '')
    admin_id = call.from_user.id
    admin_name = call.from_user.first_name
    
    # التحقق من أن المستخدم هو المالك
    if admin_id != ADMIN_ID:
        return bot.answer_callback_query(call.id, "⛔ غير مصرح لك!", show_alert=True)
    
    # التحقق من وجود الطلب
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو تم حذفه!", show_alert=True)
    
    order = active_orders[order_id]
    
    # التحقق من أن الطلب لم يتم استلامه مسبقاً
    if order['status'] == 'claimed':
        return bot.answer_callback_query(call.id, "⚠️ تم استلام هذا الطلب مسبقاً!", show_alert=True)
    
    # تحديث حالة الطلب في الذاكرة
    order['status'] = 'claimed'
    order['admin_id'] = admin_id
    
    # تحديث في Firebase
    try:
        db.collection('orders').document(order_id).update({
            'status': 'claimed',
            'admin_id': str(admin_id),
            'claimed_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"⚠️ خطأ في تحديث الطلب في Firebase: {e}")
    
    # تحديث رسالة المشرف الذي استلم
    try:
        bot.edit_message_text(
            f"✅ تم استلام الطلب #{order_id}\n\n"
            f"📦 المنتج: {order['item_name']}\n"
            f"💰 السعر: {order['price']} ريال\n\n"
            f"👨‍💼 أنت المسؤول عن هذا الطلب\n"
            f"⏰ الحالة: قيد التنفيذ...\n\n"
            f"🔒 سيتم إرسال البيانات السرية لك الآن...",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    except:
        pass
    
    # حذف الرسالة من المشرفين الآخرين
    if 'admin_messages' in order:
        for other_admin_id, msg_id in order['admin_messages'].items():
            if other_admin_id != admin_id:
                try:
                    bot.delete_message(other_admin_id, msg_id)
                except:
                    pass
    
    # إرسال البيانات المخفية للمشرف على الخاص
    hidden_info = order['hidden_data'] if order['hidden_data'] else "لا توجد بيانات مخفية لهذا المنتج."
    
    # إنشاء زر لتأكيد إتمام الطلب
    markup = types.InlineKeyboardMarkup()
    complete_btn = types.InlineKeyboardButton("✅ تم التسليم للعميل", callback_data=f"complete_{order_id}")
    markup.add(complete_btn)
    
    bot.send_message(
        admin_id,
        f"🔐 بيانات الطلب السرية #{order_id}\n\n"
        f"📦 المنتج: {order['item_name']}\n\n"
        f"👤 معلومات العميل:\n"
        f"• الاسم: {order['buyer_name']}\n"
        f"• آيدي تيليجرام: {order['buyer_id']}\n"
        f"• آيدي اللعبة: {order['game_id']}\n"
        f"• الاسم في اللعبة: {order['game_name']}\n\n"
        f"🔒 البيانات المحمية:\n"
        f"{hidden_info}\n\n"
        f"⚡ قم بتنفيذ الطلب ثم اضغط الزر أدناه!",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id, "✅ تم استلام الطلب! تحقق من رسائلك الخاصة.")

# زر إتمام الطلب من قبل المشرف (النظام القديم - للطلبات في الذاكرة)
@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_') and not call.data.startswith('complete_order_'))
def complete_order(call):
    order_id = call.data.replace('complete_', '')
    admin_id = call.from_user.id
    
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "❌ الطلب غير موجود!", show_alert=True)
    
    order = active_orders[order_id]
    
    # التحقق من أن المشرف هو نفسه من استلم الطلب
    if order['admin_id'] != admin_id:
        return bot.answer_callback_query(call.id, "⛔ لم تستلم هذا الطلب!", show_alert=True)
    
    # تحويل المال للبائع
    add_balance(order['seller_id'], order['price'])
    
    # إشعار البائع
    bot.send_message(
        order['seller_id'],
        f"💰 تم بيع منتجك!\n\n"
        f"📦 المنتج: {order['item_name']}\n"
        f"💵 المبلغ: {order['price']} ريال\n\n"
        f"✅ تم إضافة المبلغ لرصيدك!"
    )
    
    # إشعار العميل
    markup = types.InlineKeyboardMarkup()
    confirm_btn = types.InlineKeyboardButton("✅ أكد الاستلام", callback_data=f"buyer_confirm_{order_id}")
    markup.add(confirm_btn)
    
    bot.send_message(
        order['buyer_id'],
        f"🎉 تم تنفيذ طلبك!\n\n"
        f"📦 المنتج: {order['item_name']}\n\n"
        f"✅ يرجى التحقق من حسابك والتأكد من استلام الخدمة\n\n"
        f"⚠️ إذا استلمت الخدمة بنجاح، اضغط الزر أدناه لتأكيد الاستلام.",
        reply_markup=markup
    )
    
    # تحديث حالة الطلب
    order['status'] = 'completed'
    
    # حذف رسالة البيانات السرية من خاص المشرف
    try:
        bot.edit_message_text(
            f"✅ تم إتمام الطلب #{order_id}\n\nتم حذف البيانات السرية للأمان.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
    except:
        pass
    
    bot.answer_callback_query(call.id, "✅ تم إتمام الطلب بنجاح!")

# زر تأكيد الاستلام من العميل
@bot.callback_query_handler(func=lambda call: call.data.startswith('buyer_confirm_'))
def buyer_confirm(call):
    order_id = call.data.replace('buyer_confirm_', '')
    
    if order_id not in active_orders:
        return bot.answer_callback_query(call.id, "✅ تم تأكيد هذا الطلب مسبقاً!")
    
    order = active_orders[order_id]
    
    # التحقق من أن المستخدم هو المشتري
    if str(call.from_user.id) != order['buyer_id']:
        return bot.answer_callback_query(call.id, "⛔ هذا ليس طلبك!", show_alert=True)
    
    # حذف الطلب من القائمة النشطة
    del active_orders[order_id]
    
    # تحديث في Firebase
    try:
        db.collection('orders').document(order_id).update({
            'status': 'confirmed',
            'confirmed_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"⚠️ خطأ في تحديث الطلب في Firebase: {e}")
    
    bot.edit_message_text(
        f"✅ شكراً لتأكيدك!\n\n"
        f"تم إتمام الطلب بنجاح ✨\n"
        f"نتمنى لك تجربة ممتعة! 🎮",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    bot.answer_callback_query(call.id, "✅ شكراً لك!")

# زر تأكيد الاستلام (يحرر المال للبائع) - الكود القديم للتوافق
@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_'))
def confirm_transaction(call):
    trans_id = call.data.split('_')[1]
    
    if trans_id not in transactions:
        return bot.answer_callback_query(call.id, "هذه العملية غير موجودة")
    
    trans = transactions[trans_id]
    
    # التأكد أن الذي يضغط هو المشتري فقط
    if str(call.from_user.id) != str(trans['buyer_id']):
        return bot.answer_callback_query(call.id, "فقط المشتري يمكنه تأكيد الاستلام!", show_alert=True)

    # تحرير المال للبائع
    seller_id = trans['seller_id']
    amount = trans['amount']
    
    # إضافة الرصيد للبائع
    add_balance(seller_id, amount)
    
    # حذف العملية من الانتظار
    del transactions[trans_id]
    
    bot.edit_message_text(f"✅ تم تأكيد استلام الخدمة: {trans['item_name']}\nتم تحويل {amount} ريال للبائع.", call.message.chat.id, call.message.message_id)
    bot.send_message(seller_id, f"🤑 مبروك! قام العميل بتأكيد الاستلام.\n💰 تم إضافة {amount} ريال لرصيدك.\n📦 الطلب: {trans['item_name']}\n🎮 آيدي: {trans.get('game_id', 'غير محدد')}")

# معالج تنفيذ الطلبات اليدوية
@bot.callback_query_handler(func=lambda call: call.data.startswith('claim_order_'))
def claim_manual_order(call):
    """معالج تنفيذ الطلب اليدوي من قبل الأدمن أو المشرف"""
    order_id = call.data.replace('claim_order_', '')
    admin_id = call.from_user.id
    admin_name = call.from_user.first_name
    
    print(f"📋 محاولة استلام الطلب: {order_id} بواسطة: {admin_name} ({admin_id})")
    
    # التحقق من أن المستخدم هو المالك أو مشرف
    is_owner = (admin_id == ADMIN_ID)
    is_manager = False
    
    if not is_owner and db:
        try:
            admins = db.collection('admins').where('telegram_id', '==', str(admin_id)).get()
            is_manager = len(list(admins)) > 0
        except:
            pass
    
    if not is_owner and not is_manager:
        return bot.answer_callback_query(call.id, "⛔ غير مصرح لك!", show_alert=True)
    
    try:
        # جلب الطلب من Firebase
        order_ref = db.collection('orders').document(order_id)
        order_doc = order_ref.get()
        
        print(f"🔍 البحث عن الطلب: {order_id} - موجود: {order_doc.exists}")
        
        if not order_doc.exists:
            print(f"❌ الطلب غير موجود في Firebase: {order_id}")
            return bot.answer_callback_query(call.id, "❌ الطلب غير موجود!", show_alert=True)
        
        order = order_doc.to_dict()
        
        # التحقق من حالة الطلب
        if order.get('status') == 'completed':
            return bot.answer_callback_query(call.id, "✅ تم تنفيذ هذا الطلب مسبقاً!", show_alert=True)
        
        if order.get('status') == 'claimed':
            claimed_by = order.get('claimed_by_name', 'أدمن آخر')
            return bot.answer_callback_query(call.id, f"⚠️ هذا الطلب مستلم من قبل {claimed_by}!", show_alert=True)
        
        # تحديث حالة الطلب إلى مستلم
        order_ref.update({
            'status': 'claimed',
            'claimed_by': str(admin_id),
            'claimed_by_name': admin_name,
            'claimed_at': firestore.SERVER_TIMESTAMP
        })
        
        # تحديث رسالة الأدمن
        try:
            buyer_details = order.get('buyer_details', '')
            
            # 🔓 الآن نكشف بيانات المشتري للمشرف الذي استلم الطلب
            buyer_details_text = ""
            if buyer_details:
                buyer_details_text = f"\n\n📝 تفاصيل الطلب من المشتري:\n━━━━━━━━━━━━━━━━━━━━━━━━\n{buyer_details}\n━━━━━━━━━━━━━━━━━━━━━━━━"
            
            # إنشاء زر إكمال الطلب
            complete_markup = telebot.types.InlineKeyboardMarkup()
            complete_markup.add(telebot.types.InlineKeyboardButton(
                "✅ تم التسليم", 
                callback_data=f"complete_order_{order_id}"
            ))
            
            bot.edit_message_text(
                f"✅ تم استلام الطلب بواسطتك!\n\n"
                f"🆔 رقم الطلب: #{order_id}\n"
                f"📦 المنتج: {order.get('item_name')}\n"
                f"👤 المشتري: {order.get('buyer_name')}\n"
                f"🔢 معرف المشتري: {order.get('buyer_id')}\n"
                f"💰 السعر: {order.get('price')} ريال"
                f"{buyer_details_text}\n\n"
                f"👇 بعد تنفيذ الطلب اضغط الزر أدناه",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=complete_markup
            )
        except Exception as e:
            print(f"⚠️ خطأ في تحديث رسالة الأدمن: {e}")
        
        # 📌 إشعار المالك بأن مشرف استلم الطلب
        if admin_id != ADMIN_ID:
            try:
                bot.send_message(
                    ADMIN_ID,
                    f"📌 تم استلام طلب بواسطة مشرف\n\n"
                    f"🆔 رقم الطلب: #{order_id}\n"
                    f"📦 المنتج: {order.get('item_name')}\n"
                    f"👤 المشتري: {order.get('buyer_name')}\n"
                    f"👨‍💼 المشرف المنفذ: {admin_name}\n"
                    f"💰 السعر: {order.get('price')} ريال"
                )
            except:
                pass
        
        # إشعار المشتري باسم المشرف الذي استلم
        try:
            bot.send_message(
                int(order.get('buyer_id')),
                f"👨‍💼 تم استلام طلبك!\n\n"
                f"🆔 رقم الطلب: #{order_id}\n"
                f"📦 المنتج: {order.get('item_name')}\n"
                f"✅ المسؤول عن طلبك: {admin_name}\n\n"
                f"⏳ جاري تنفيذ طلبك..."
            )
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ تم استلام الطلب بنجاح!")
        
    except Exception as e:
        print(f"❌ خطأ في استلام الطلب: {e}")
        bot.answer_callback_query(call.id, f"❌ حدث خطأ: {str(e)}", show_alert=True)

# معالج إكمال الطلب اليدوي
@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_order_'))
def complete_manual_order(call):
    """معالج إكمال الطلب اليدوي بعد التنفيذ"""
    from datetime import datetime
    order_id = call.data.replace('complete_order_', '')
    admin_id = call.from_user.id
    admin_name = call.from_user.first_name
    
    try:
        # جلب الطلب من Firebase
        order_ref = db.collection('orders').document(order_id)
        order_doc = order_ref.get()
        
        if not order_doc.exists:
            return bot.answer_callback_query(call.id, "❌ الطلب غير موجود!", show_alert=True)
        
        order = order_doc.to_dict()
        
        # التحقق من أن الأدمن هو من استلم الطلب أو المالك
        is_claimer = (order.get('claimed_by') == str(admin_id))
        is_owner = (admin_id == ADMIN_ID)
        
        if not is_claimer and not is_owner:
            return bot.answer_callback_query(call.id, "⛔ هذا الطلب ليس مستلماً بواسطتك!", show_alert=True)
        
        if order.get('status') == 'completed':
            return bot.answer_callback_query(call.id, "✅ تم تنفيذ هذا الطلب مسبقاً!", show_alert=True)
        
        # تحديث حالة الطلب إلى مكتمل
        order_ref.update({
            'status': 'completed',
            'completed_by': str(admin_id),
            'completed_by_name': admin_name,
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        
        # تحديث رسالة الأدمن
        try:
            bot.edit_message_text(
                f"✅ تم إكمال الطلب بنجاح!\n\n"
                f"🆔 رقم الطلب: #{order_id}\n"
                f"📦 المنتج: {order.get('item_name')}\n"
                f"👤 المشتري: {order.get('buyer_name')}\n"
                f"💰 السعر: {order.get('price')} ريال\n\n"
                f"👨‍💼 تم التنفيذ بواسطة: {admin_name}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        except:
            pass
        
        # إشعار المشتري بإكمال الطلب
        try:
            hidden_data = order.get('hidden_data', '')
            if hidden_data:
                bot.send_message(
                    int(order.get('buyer_id')),
                    f"🎉 تم تنفيذ طلبك بنجاح!\n\n"
                    f"🆔 رقم الطلب: #{order_id}\n"
                    f"📦 المنتج: {order.get('item_name')}\n"
                    f"👨‍💼 تم التنفيذ بواسطة: {admin_name}\n\n"
                    f"🔐 بيانات الاشتراك:\n{hidden_data}\n\n"
                    f"⚠️ احفظ هذه البيانات في مكان آمن!\n"
                    f"شكراً لتسوقك معنا! 💙"
                )
            else:
                bot.send_message(
                    int(order.get('buyer_id')),
                    f"🎉 تم تنفيذ طلبك بنجاح!\n\n"
                    f"🆔 رقم الطلب: #{order_id}\n"
                    f"📦 المنتج: {order.get('item_name')}\n"
                    f"👨‍💼 تم التنفيذ بواسطة: {admin_name}\n\n"
                    f"شكراً لتسوقك معنا! 💙"
                )
        except Exception as e:
            print(f"⚠️ فشل إشعار المشتري: {e}")
        
        # إشعار المالك الرئيسي
        try:
            if admin_id != ADMIN_ID:
                bot.send_message(
                    ADMIN_ID,
                    f"✅ تم تنفيذ طلب يدوي\n\n"
                    f"🆔 الطلب: #{order_id}\n"
                    f"📦 المنتج: {order.get('item_name')}\n"
                    f"👨‍💼 المنفذ: {admin_name}\n"
                    f"👤 المشتري: {order.get('buyer_name')}"
                )
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ تم إكمال الطلب وإشعار المشتري!")
        
    except Exception as e:
        print(f"❌ خطأ في إكمال الطلب: {e}")
        bot.answer_callback_query(call.id, f"❌ حدث خطأ: {str(e)}", show_alert=True)

