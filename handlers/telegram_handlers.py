#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تعريف وتسجيل معالجات بوت التيليجرام
=====================================
"""

import time
import random
import uuid
from telebot import types

# سيتم استيراد bot و extensions من app الرئيسي
def register_telegram_handlers(bot, extensions, firebase_utils, config, payment):
    """
    تسجيل جميع معالجات بوت التيليجرام
    
    Parameters:
    -----------
    bot : telebot.TeleBot
        instance بوت التيليجرام
    extensions : module
        وحدة الإعدادات الخارجية
    firebase_utils : module
        أدوات Firebase
    config : module
        ملف الإعدادات
    payment : module
        وحدة نظام الدفع
    """
    
    # استخراج المتغيرات المطلوبة
    ADMIN_ID = extensions.ADMIN_ID
    TOKEN = extensions.TOKEN
    SITE_URL = extensions.SITE_URL
    verification_codes = extensions.verification_codes
    user_states = extensions.user_states
    
    db = extensions.db
    
    # استخراج الدوال من firebase_utils
    get_all_products_for_store = firebase_utils.get_all_products_for_store
    get_categories = firebase_utils.get_categories
    
    # تخزين مؤقت
    temp_product_data = {}
    
    # ===== دوال مساعدة =====
    
    def log_message(message, handler_name):
        """طباعة سجل الرسالة"""
        print("="*50)
        print(f"📨 {handler_name}")
        print(f"👤 المستخدم: {message.from_user.id} - {message.from_user.first_name}")
        print(f"💬 النص: {message.text if hasattr(message, 'text') else 'N/A'}")
        print("="*50)
    
    def get_user_profile_photo(user_id):
        """جلب صورة البروفايل من تيليجرام"""
        try:
            photos = bot.get_user_profile_photos(int(user_id), limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][0].file_id
                file_info = bot.get_file(file_id)
                photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
                return photo_url
            return None
        except Exception as e:
            print(f"⚠️ خطأ في جلب صورة البروفايل: {e}")
            return None
    
    def generate_verification_code(user_id, user_name):
        """توليد كود تحقق عشوائي"""
        code = str(random.randint(100000, 999999))
        verification_codes[str(user_id)] = {
            'code': code,
            'name': user_name,
            'created_at': time.time()
        }
        return code
    
    def verify_code(user_id, code):
        """التحقق من صحة الكود"""
        user_id = str(user_id)
        
        if user_id not in verification_codes:
            return None
        
        code_data = verification_codes[user_id]
        
        # التحقق من صلاحية الكود (10 دقائق)
        if time.time() - code_data['created_at'] > 600:
            del verification_codes[user_id]
            return None
        
        # التحقق من تطابق الكود
        if code_data['code'] != code:
            return None
        
        return code_data
    
    # ===== معالجات البوت =====
    
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        """معالج أمر /start"""
        log_message(message, "معالج /start")
        try:
            user_id = str(message.from_user.id)
            user_name = message.from_user.first_name
            if message.from_user.last_name:
                user_name += ' ' + message.from_user.last_name
            username = message.from_user.username or ''
            
            # جلب صورة البروفايل
            profile_photo = get_user_profile_photo(user_id)
            
            # حفظ معلومات المستخدم في Firebase
            if db:
                try:
                    from firebase_admin import firestore
                    user_ref = db.collection('users').document(user_id)
                    user_doc = user_ref.get()
                    
                    if not user_doc.exists:
                        user_data = {
                            'telegram_id': user_id,
                            'name': user_name,
                            'username': username,
                            'balance': 0.0,
                            'telegram_started': True,
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
                            'telegram_started': True,
                            'last_seen': firestore.SERVER_TIMESTAMP
                        }
                        if profile_photo:
                            update_data['profile_photo'] = profile_photo
                        user_ref.update(update_data)
                        print(f"✅ مستخدم موجود تم تحديثه")
                except Exception as e:
                    print(f"⚠️ خطأ في Firebase: {e}")
            
            # إنشاء أزرار Inline
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_shop = types.InlineKeyboardButton("🏪 افتح السوق", callback_data="open_shop")
            btn_code = types.InlineKeyboardButton("🔐 كود الدخول", callback_data="get_code")
            btn_myid = types.InlineKeyboardButton("🆔 معرفي", callback_data="my_id")
            markup.add(btn_shop)
            markup.add(btn_code, btn_myid)
            
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
    
    @bot.message_handler(commands=['my_id'])
    def my_id(message):
        """معالج أمر /my_id"""
        log_message(message, "معالج /my_id")
        try:
            bot.reply_to(
                message, 
                f"🆔 الآيدي الخاص بك: `{message.from_user.id}`\n\n"
                f"أرسل هذا الرقم للمالك ليضيفك كمشرف!",
                parse_mode="Markdown"
            )
            print(f"✅ تم إرسال الآيدي")
        except Exception as e:
            print(f"❌ خطأ: {e}")
    
    @bot.message_handler(commands=['code'])
    def get_verification_code(message):
        """معالج أمر /code"""
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += ' ' + message.from_user.last_name
        
        code = generate_verification_code(user_id, user_name)
        
        bot.send_message(
            message.chat.id,
            f"🔐 *كود التحقق الخاص بك:*\n\n"
            f"`{code}`\n\n"
            f"⏱️ **صالح لمدة 10 دقائق**\n\n"
            f"💡 **خطوات الدخول:**\n"
            f"1️⃣ افتح الموقع في المتصفح\n"
            f"2️⃣ اضغط على زر 'حسابي'\n"
            f"3️⃣ أدخل الآيدي الخاص بك: `{user_id}`\n"
            f"4️⃣ أدخل الكود أعلاه\n\n"
            f"⚠️ لا تشارك هذا الكود مع أحد!",
            parse_mode="Markdown"
        )
    
    # معالج أزرار Inline
    @bot.callback_query_handler(func=lambda call: call.data in ["open_shop", "get_code", "my_id"])
    def handle_inline_buttons(call):
        """معالج أزرار Inline"""
        try:
            if call.data == "open_shop":
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
            elif call.data == "get_code":
                user_id = str(call.from_user.id)
                user_name = call.from_user.first_name
                if call.from_user.last_name:
                    user_name += ' ' + call.from_user.last_name
                code = str(random.randint(100000, 999999))
                verification_codes[user_id] = {
                    'code': code,
                    'name': user_name,
                    'created_at': time.time()
                }
                bot.send_message(
                    call.message.chat.id,
                    f"🔐 *كود الدخول الخاص بك:*\n\n"
                    f"`{code}`\n\n"
                    f"⏱ صالح لمدة 10 دقائق\n"
                    f"📋 انسخ الكود وأدخله في الموقع",
                    parse_mode="Markdown"
                )
            elif call.data == "my_id":
                bot.send_message(
                    call.message.chat.id,
                    f"🆔 *الآيدي الخاص بك:*\n\n"
                    f"`{call.from_user.id}`\n\n"
                    f"أرسل هذا الرقم للمالك ليضيفك كمشرف!",
                    parse_mode="Markdown"
                )
            
            bot.answer_callback_query(call.id)
        except Exception as e:
            print(f"❌ خطأ في inline button: {e}")
            bot.answer_callback_query(call.id, "حدث خطأ!")
    
    print("✅ تم تسجيل معالجات بوت التيليجرام")
