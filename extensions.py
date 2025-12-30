#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extensions.py - الكائنات المشتركة بين الملفات
يحل مشكلة Circular Imports
"""

import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, firestore
import telebot

# إعداد التسجيل
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# --- Firebase ---
db = None
FIREBASE_AVAILABLE = False

def init_firebase():
    """تهيئة Firebase"""
    global db, FIREBASE_AVAILABLE
    
    try:
        if firebase_admin._apps:
            # Firebase مهيأ مسبقاً
            db = firestore.client()
            FIREBASE_AVAILABLE = True
            return db
            
        # التحقق من المتغير البيئي أولاً (للإنتاج في Render)
        firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS")
        
        if firebase_credentials_json:
            # استخدام المتغير البيئي (Render)
            cred_dict = json.loads(firebase_credentials_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            FIREBASE_AVAILABLE = True
            print("✅ Firebase: متصل (المتغير البيئي)")
        elif os.path.exists('serviceAccountKey.json'):
            # استخدام الملف المحلي (للتطوير)
            cred = credentials.Certificate('serviceAccountKey.json')
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            FIREBASE_AVAILABLE = True
            print("✅ Firebase: متصل (ملف محلي)")
        else:
            print("⚠️ Firebase: لا يوجد credentials")
            FIREBASE_AVAILABLE = False
            
    except Exception as e:
        print(f"⚠️ Firebase غير متاح: {e}")
        FIREBASE_AVAILABLE = False
        db = None
    
    return db

# --- الإعدادات الأساسية ---
# تحويل ADMIN_ID إلى integer للمقارنة مع from_user.id
_admin_id_str = os.getenv('ADMIN_ID', '0')
try:
    ADMIN_ID = int(_admin_id_str)
except ValueError:
    ADMIN_ID = 0
    print(f"⚠️ ADMIN_ID غير صالح: {_admin_id_str}")

TOKEN = os.getenv('BOT_TOKEN', 'default_token_change_me')
SITE_URL = os.getenv('SITE_URL', 'https://tr-ozni.onrender.com')
SECRET_KEY = os.getenv('SECRET_KEY', '')

# EdfaPay
EDFAPAY_MERCHANT_ID = os.getenv('EDFAPAY_MERCHANT_ID', '')
EDFAPAY_PASSWORD = os.getenv('EDFAPAY_PASSWORD', '')

# --- البيانات المؤقتة (لا تُخزن في Firebase) ---
# هذه البيانات مؤقتة فقط ولا تحتاج حفظ دائم
verification_codes = {}      # أكواد التحقق المؤقتة
user_states = {}            # حالات المستخدمين (للبوت)
display_settings = {'categories_columns': 3}  # إعدادات العرض

# ملاحظة: تم إزالة users_wallets, marketplace_items, categories_list, user_carts
# كل البيانات الآن تُجلب مباشرة من Firebase

# --- تهيئة Firebase عند الاستيراد ---
init_firebase()

# --- إنشاء البوت ---
bot = None
BOT_ACTIVE = False
BOT_USERNAME = ""

def init_bot():
    """تهيئة البوت"""
    global bot, BOT_ACTIVE, BOT_USERNAME
    
    if TOKEN.startswith("default_token"):
        print("⚠️ BOT_TOKEN غير محدد - استخدم متغير البيئة BOT_TOKEN")
        bot = telebot.TeleBot("123456789:dummy_token")
        BOT_ACTIVE = False
        BOT_USERNAME = ""
    else:
        try:
            bot = telebot.TeleBot(TOKEN)
            telebot.apihelper.RETRY_ON_ERROR = True
            BOT_ACTIVE = True
            try:
                bot_info = bot.get_me()
                BOT_USERNAME = bot_info.username
                print(f"✅ البوت: متصل بنجاح (@{BOT_USERNAME})")
            except:
                BOT_USERNAME = ""
                print(f"✅ البوت: متصل بنجاح")
        except Exception as e:
            BOT_ACTIVE = False
            BOT_USERNAME = ""
            bot = telebot.TeleBot("dummy_token")
            print(f"⚠️ البوت غير متاح: {e}")
    
    return bot

# تهيئة البوت عند الاستيراد
init_bot()
