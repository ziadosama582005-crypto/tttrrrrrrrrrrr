#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
التطبيق الرئيسي - متجر رقمي مع بوت تيليجرام
"""

import os
import html
import logging
import telebot
from telebot import types
from flask import Flask, request, render_template_string, render_template, redirect, session, jsonify, url_for, send_from_directory
import json
import random
import hashlib
import time
import uuid
import requests
from datetime import datetime

# استيراد FieldFilter للنسخ الجديدة من Firestore
try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    USE_FIELD_FILTER = True
except ImportError:
    USE_FIELD_FILTER = False

# === استيراد الملفات المفصولة ===
from extensions import (
    db, FIREBASE_AVAILABLE, logger,
    ADMIN_ID, TOKEN, SITE_URL, SECRET_KEY,
    EDFAPAY_MERCHANT_ID, EDFAPAY_PASSWORD,
    verification_codes, user_states, display_settings,
    bot, BOT_ACTIVE, BOT_USERNAME
)
from config import (
    EDFAPAY_API_URL, SESSION_CONFIG, IS_PRODUCTION,
    RATE_LIMIT_DEFAULT, DEFAULT_CATEGORIES, CART_EXPIRY_HOURS,
    CONTACT_BOT_URL, CONTACT_WHATSAPP
)
from firebase_utils import (
    query_where, get_balance, add_balance, deduct_balance,
    get_products, get_product_by_id, add_product, update_product, mark_product_sold, delete_product,
    get_categories, add_category, update_category, delete_category, get_category_by_id,
    get_charge_key, use_charge_key, create_charge_key,
    get_user_cart, save_user_cart, clear_user_cart, get_all_carts,
    get_all_products_for_store, get_sold_products, get_all_users, get_all_charge_keys,
    get_active_orders, get_products_by_category, count_products_in_category,
    save_pending_payment, get_pending_payment, update_pending_payment, add_purchase_history,
    get_header_settings, get_collection_data, get_collection_list,
    add_balance_log, get_balance_logs, get_all_balance_logs,
    get_user_purchases, get_all_purchases
)
from payment import (
    calculate_hash, create_payment_payload,
    create_edfapay_invoice as create_edfapay_invoice_util,
    register_callback_url, check_callback_url
)
from utils import sanitize, regenerate_session, generate_code, validate_phone

# استيراد نظام الإشعارات
from notifications import (
    notify_owner, notify_all_admins, notify_new_charge,
    notify_withdrawal_request, notify_new_purchase, notify_new_order,
    notify_new_user, notify_product_sold,
    notify_invoice_created, notify_payment_pending,
    notify_payment_success, notify_payment_failed, notify_recharge_request,
    send_order_email
)

# استيراد أدوات التشفير
try:
    from encryption_utils import encrypt_data, decrypt_data
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    encrypt_data = lambda x: x
    decrypt_data = lambda x: x
    print("⚠️ encryption_utils غير متوفرة - التشفير معطل")

# استيراد نظام المسارات المفصولة (Blueprints)
from routes import cart_bp, init_cart, wallet_bp, init_wallet, admin_bp, init_admin
from routes.api_routes import api_bp
from routes.web_routes import web_bp
from routes.auth_routes import auth_bp
from routes.payment_routes import payment_bp, set_merchant_invoices
from routes.profile import profile_bp
from routes.recharge import recharge_bp

# استيراد معالجات البوت
from telegram import bot_handlers

# استيراد security middleware
from security_middleware import (
    get_csrf_token, inject_security_context,
    detect_new_login, refresh_session,
    set_csrf_cookie,  # 🔐 Double Submit Cookie
    # 🔒 Security Logging
    set_security_db, log_security_event, SecurityEvent,
    log_login_success, log_login_failed, log_admin_login,
    log_suspicious_activity, log_purchase, log_withdrawal
)

# استيراد Firestore للعمليات المتقدمة
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

# البوت يتم استيراده من extensions.py (تم إنشاؤه هناك)
# bot, BOT_ACTIVE, BOT_USERNAME متاحين من الاستيراد أعلاه

app = Flask(__name__)

# --- إعدادات الأمان من config ---
app.secret_key = SECRET_KEY
app.config.update(SESSION_CONFIG)

# --- Rate Limiting (تحديد المحاولات) ---
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=RATE_LIMIT_DEFAULT,
    storage_uri="memory://",
)

# --- إعدادات الشريط أعلى الهيدر (حقن للقوالب) ---
_header_settings_cache = None
_header_settings_cache_at = 0.0
_HEADER_SETTINGS_CACHE_TTL_SECONDS = 30


@app.context_processor
def inject_header_settings():
    """حقن إعدادات الشريط أعلى الهيدر لكل القوالب."""
    global _header_settings_cache, _header_settings_cache_at

    try:
        now = time.time()
        if _header_settings_cache is not None and (now - _header_settings_cache_at) < _HEADER_SETTINGS_CACHE_TTL_SECONDS:
            return {'header_settings': _header_settings_cache}

        settings = get_header_settings() if callable(get_header_settings) else {'enabled': False, 'text': '', 'link_url': ''}
        _header_settings_cache = settings
        _header_settings_cache_at = now
        return {'header_settings': settings}
    except Exception:
        return {'header_settings': {'enabled': False, 'text': '', 'link_url': ''}}


@app.context_processor
def inject_csrf():
    """حقن CSRF token لجميع القوالب"""
    return inject_security_context()

# --- Security Headers ---
@app.after_request
def add_security_headers(response):
    """إضافة رؤوس أمان للحماية من الهجمات"""
    # 1. منع تخمين نوع المحتوى
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # 2. منع تضمين الموقع في iframe (حماية من Clickjacking)
    response.headers['X-Frame-Options'] = 'DENY'
    
    # 3. حماية من XSS
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # 4. سياسة الإحالة
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # 5. 🔒 HSTS - إجبار استخدام HTTPS (سنة كاملة)
    if IS_PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    
    # 6. 🔒 CSP - Content Security Policy (حماية من XSS)
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https: blob:; "
        "connect-src 'self' https://api.edfapay.com https://api.telegram.org; "
        "frame-src 'self' https://edfapay.com https://*.edfapay.com; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    response.headers['Content-Security-Policy'] = csp_policy
    
    # 7. إخفاء معلومات السيرفر
    response.headers['Server'] = 'Protected'
    
    # 8. منع الكشف عن الإصدارات
    response.headers['X-Powered-By'] = ''
    
    # 9. 🔐 Double Submit Cookie للـ CSRF
    try:
        set_csrf_cookie(response)
    except Exception:
        pass  # تجاهل الأخطاء لعدم تعطيل الاستجابة
    
    return response


# --- حظر المسارات المشبوهة والهجمات (محسّن لتجنب الإيجابيات الخاطئة) ---
@app.before_request
def block_suspicious_requests():
    """حظر الطلبات المشبوهة قبل معالجتها وتخفيف الضغط"""
    path = request.path.lower()
    
    # 1. قائمة الامتدادات المحظورة (يجب أن تكون في نهاية الرابط)
    # نستخدم endswith للتأكد أنها امتداد ملف وليست جزءاً من كلمة
    blocked_extensions = ('.php', '.aspx', '.jsp', '.env', '.git', '.sql', '.bak')
    
    if path.endswith(blocked_extensions):
        logger.warning(f"🚫 حظر مسار مشبوه (امتداد): {path} من {request.remote_addr}")
        return "Forbidden", 403
    
    # 2. كلمات محظورة كمسارات (وليس كجزء من اسم منتج)
    # هذه خطيرة فقط إذا جاءت كمسار أساسي في بداية الرابط
    suspicious_paths = [
        '/wp-admin', '/wp-login', '/wp-content', '/wp-includes',
        '/xmlrpc', '/phpmyadmin', '/actuator', '/.env', '/.git',
        '/config.js', '/admin.php', '/shell.php'
    ]
    
    # فحص إذا كان المسار يبدأ بأحد المسارات المشبوهة
    for suspicious in suspicious_paths:
        if path.startswith(suspicious) or path == suspicious.lstrip('/'):
            logger.warning(f"🚫 حظر مسار مشبوه: {path} من {request.remote_addr}")
            return "Forbidden", 403
    
    # 3. حظر المسارات التي تحتوي على /wordpress/ كمجلد
    if '/wordpress/' in path or path.startswith('/wordpress'):
        logger.warning(f"🚫 حظر مسار WordPress: {path} من {request.remote_addr}")
        return "Forbidden", 403
    
    # 4. حظر مسارات الاختراق الإضافية
    extra_blocked = [
        '/pma', '/wp-config', '/config.php',
        '/shell', '/c99', '/r57', '/webshell', '/backdoor',
        '/.htaccess', '/.htpasswd', '/cgi-bin', '/admin/config',
        '/phpinfo', '/info.php', '/test.php', '/debug',
        '/backup', '/vendor/', '/node_modules/', '/.DS_Store'
    ]
    for blocked in extra_blocked:
        if blocked in path:
            logger.warning(f"🚫 حظر مسار مشبوه: {path} من {request.remote_addr}")
            return "Forbidden", 403
    
    # 5. معالجة طلبات POST العشوائية على الصفحة الرئيسية
    if request.method == 'POST':
        # المسارات المسموح بها للـ POST (يجب أن تكون دقيقة)
        allowed_post_prefixes = [
            '/webhook', '/api/', '/auth/', '/payment/', '/cart/',
            '/admin/', '/profile/', '/wallet/', '/charge/', '/login',
            '/telegram-auth', '/update', '/confirm', '/order',
            '/checkout', '/contact', '/search', '/category'
        ]
        
        # تحقق إذا كان المسار يبدأ بأحد المسارات المسموحة
        is_allowed = any(path.startswith(prefix) for prefix in allowed_post_prefixes)
        
        # حظر POST على المسارات غير المسموحة
        blocked_post_paths = ['/', '/index', '/index.php', '/home', '/admin', '/api']
        if not is_allowed and path in blocked_post_paths:
            logger.warning(f"🚫 حظر POST عشوائي على {path} من {request.remote_addr}")
            return "Forbidden", 403


# --- معالجات الأخطاء الآمنة (إخفاء المعلومات الحساسة) ---
@app.errorhandler(404)
def page_not_found(error):
    """صفحة غير موجودة"""
    return jsonify({'status': 'error', 'message': 'الصفحة غير موجودة'}), 404


@app.errorhandler(403)
def access_forbidden(error):
    """عدم الوصول (لا توجد صلاحيات)"""
    return jsonify({'status': 'error', 'message': 'لا تملك صلاحية الوصول'}), 403


@app.errorhandler(500)
def internal_error(error):
    """خطأ داخلي في السيرفر - إخفاء التفاصيل"""
    logger.error(f"❌ خطأ داخلي: {error}", exc_info=True)
    # لا نعرض تفاصيل الخطأ
    return jsonify({'status': 'error', 'message': 'حدث خطأ في السيرفر. الرجاء المحاولة لاحقاً'}), 500


@app.errorhandler(405)
def method_not_allowed(error):
    """Method Not Allowed - حظر الطرق غير المسموحة بصمت"""
    # لا نسجل تفاصيل - فقط نرفض الطلب
    return "Forbidden", 403


@app.errorhandler(Exception)
def handle_exception(error):
    """معالج شامل للأخطاء غير المتوقعة"""
    # تجاهل أخطاء 405 لأنها غالباً هجمات
    if '405' in str(error) or 'Method Not Allowed' in str(error):
        return "Forbidden", 403
    
    logger.error(f"❌ خطأ غير متوقع: {error}", exc_info=True)
    
    # لا نعرض معلومات حساسة في الأخطاء
    return jsonify({'status': 'error', 'message': 'حدث خطأ. الرجاء المحاولة لاحقاً'}), 500

# --- قواعد البيانات ---
# جميع البيانات تُجلب مباشرة من Firebase (لا توجد نسخ محلية)

# الطلبات النشطة (مؤقتة - تُحمل من Firebase عند الحاجة)
active_orders = {}

# العمليات المعلقة (المبالغ المحجوزة) - مؤقتة
transactions = {}

# أكواد دخول لوحة التحكم المؤقتة
admin_login_codes = {}

# محاولات الدخول الفاشلة (للحماية من brute force)
failed_login_attempts = {}

# طلبات الدفع المعلقة (مؤقتة - تُحمل من Firebase)
pending_payments = {}

# الفواتير المنشأة من التجار (للعملاء)
merchant_invoices = {}

# الأقسام الافتراضية (تُستخدم إذا لم تكن هناك أقسام في Firebase)
DEFAULT_CATEGORIES_FALLBACK = [
    {'id': '1', 'name': 'نتفلكس', 'image_url': 'https://i.imgur.com/netflix.png', 'order': 1, 'delivery_type': 'instant'},
    {'id': '2', 'name': 'شاهد', 'image_url': 'https://i.imgur.com/shahid.png', 'order': 2, 'delivery_type': 'instant'},
    {'id': '3', 'name': 'ديزني بلس', 'image_url': 'https://i.imgur.com/disney.png', 'order': 3, 'delivery_type': 'instant'},
    {'id': '4', 'name': 'اوسن بلس', 'image_url': 'https://i.imgur.com/osn.png', 'order': 4, 'delivery_type': 'instant'},
    {'id': '5', 'name': 'فديو بريميم', 'image_url': 'https://i.imgur.com/vedio.png', 'order': 5, 'delivery_type': 'instant'},
    {'id': '6', 'name': 'اشتراكات أخرى', 'image_url': 'https://i.imgur.com/other.png', 'order': 6, 'delivery_type': 'manual'}
]

# 🔒 تهيئة نظام Security Logging
if db:
    set_security_db(db)
    logger.info("✅ تم ربط Security Logging بقاعدة البيانات")

# ====== تسجيل Blueprints ======
# تهيئة وتسجيل نظام السلة
init_cart(bot, ADMIN_ID, limiter)
app.register_blueprint(cart_bp)

# تهيئة وتسجيل نظام المحفظة
init_wallet(
    merchant_id=EDFAPAY_MERCHANT_ID,
    password=EDFAPAY_PASSWORD,
    api_url=EDFAPAY_API_URL,
    site_url=SITE_URL,
    payments_dict=pending_payments,
    app_limiter=limiter
)
app.register_blueprint(wallet_bp)

# تهيئة وتسجيل لوحة التحكم
init_admin(db, bot, ADMIN_ID, limiter, BOT_ACTIVE)
app.register_blueprint(admin_bp)

# تسجيل API Blueprint
app.register_blueprint(api_bp)

# تسجيل Web Blueprint
app.register_blueprint(web_bp)

# تسجيل Auth Blueprint
app.register_blueprint(auth_bp)

# تسجيل Profile Blueprint
app.register_blueprint(profile_bp)

# تسجيل Payment Blueprint
set_merchant_invoices(merchant_invoices)
app.register_blueprint(payment_bp)

# تسجيل Recharge Blueprint (الشحن الجديد)
app.register_blueprint(recharge_bp)

print("✅ تم تسجيل جميع Blueprints (السلة، المحفظة، لوحة التحكم، API، Web, Auth, Profile, Payment, Recharge)")

# دالة تحميل جميع البيانات من Firebase عند بدء التطبيق
def load_all_data_from_firebase():
    """التحقق من اتصال Firebase عند بدء التطبيق"""
    global active_orders, display_settings
    
    if not db:
        print("⚠️ Firebase غير متاح - البيانات ستُجلب مباشرة عند الحاجة")
        return
    
    try:
        print("📥 التحقق من اتصال Firebase...")
        
        # التحقق من الاتصال بجلب عدد المنتجات
        products = get_all_products_for_store()
        print(f"✅ Firebase متصل - {len(products)} منتج متاح")
        
        # تحميل الأقسام للتحقق
        categories = get_categories()
        if categories:
            print(f"✅ تم جلب {len(categories)} قسم")
        else:
            print(f"ℹ️ لا توجد أقسام - سيتم استخدام الأقسام الافتراضية")
        
        # تحميل إعدادات العرض
        try:
            settings_doc = db.collection('settings').document('display').get()
            if settings_doc.exists:
                settings_data = settings_doc.to_dict()
                display_settings['categories_columns'] = settings_data.get('categories_columns', 3)
                print(f"✅ إعدادات العرض (أعمدة: {display_settings['categories_columns']})")
        except Exception as e:
            print(f"⚠️ خطأ في تحميل إعدادات العرض: {e}")
        
        print("🎉 Firebase جاهز للعمل!")
        
    except Exception as e:
        print(f"❌ خطأ في الاتصال بـ Firebase: {e}")

# --- دوال مساعدة ---

def get_categories_list():
    """جلب الأقسام من Firebase أو استخدام الافتراضية"""
    categories = get_categories()
    if categories:
        return categories
    return DEFAULT_CATEGORIES_FALLBACK

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



# دالة للتحقق من صحة الكود
def verify_code(user_id, code):
    user_id = str(user_id)
    
    if user_id not in verification_codes:
        return None
    
    code_data = verification_codes[user_id]
    
    # ✅ التحقق من صلاحية الكود (2 دقيقة فقط بدل 10)
    if time.time() - code_data['created_at'] > 120:  # 2 * 60 ثانية
        del verification_codes[user_id]
        return None
    
    # التحقق من تطابق الكود
    if code_data['code'] != code:
        return None
    
    return code_data

# --- مسارات الموقع (Flask) ---

# مسار جلب طلبات المستخدم
@app.route('/get_orders')
def get_user_orders():
    # استخدام الجلسة فقط للأمان - لا نقبل user_id من الرابط
    user_id = session.get('user_id')
    
    if not user_id:
        return {'orders': []}
    
    user_id = str(user_id)
    
    # جلب جميع الطلبات الخاصة بالمستخدم من Firebase
    user_orders = []
    
    try:
        orders_ref = query_where(db.collection('orders'), 'buyer_id', '==', user_id)
        for doc in orders_ref.stream():
            order = doc.to_dict()
            order_id = doc.id
            
            # إضافة اسم المشرف إذا تم استلام الطلب
            admin_name = None
            if order.get('admin_id'):
                try:
                    admin_info = bot.get_chat(order['admin_id'])
                    admin_name = admin_info.first_name
                except:
                    admin_name = "مشرف"
            
            user_orders.append({
                'order_id': order_id,
                'item_name': order.get('item_name', 'منتج'),
                'price': order.get('price', 0),
                'game_id': order.get('buyer_details', ''),  # تفاصيل المشتري
                'game_name': '',
                'status': order.get('status', 'completed'),
                'delivery_type': order.get('delivery_type', 'instant'),
                'admin_name': admin_name
            })
    except Exception as e:
        print(f"❌ خطأ في جلب الطلبات: {e}")
        # fallback للذاكرة
        for order_id, order in active_orders.items():
            if str(order.get('buyer_id')) == user_id:
                admin_name = None
                if order.get('admin_id'):
                    try:
                        admin_info = bot.get_chat(order['admin_id'])
                        admin_name = admin_info.first_name
                    except:
                        admin_name = "مشرف"
                
                user_orders.append({
                    'order_id': order_id,
                    'item_name': order.get('item_name', 'منتج'),
                    'price': order.get('price', 0),
                    'game_id': order.get('game_id', ''),
                    'game_name': order.get('game_name', ''),
                    'status': order.get('status', 'completed'),
                    'delivery_type': order.get('delivery_type', 'instant'),
                    'admin_name': admin_name
                })
    
    # ترتيب الطلبات من الأحدث للأقدم
    user_orders.reverse()
    
    return {'orders': user_orders}

# ✅ API endpoint لإرسال كود التحقق للمستخدم
@app.route('/api/send_code', methods=['POST'])
@limiter.limit("3 per minute")  # 🔒 منع الإساءة
def api_send_code():
    """إرسال كود التحقق للمستخدم عبر Telegram Bot"""
    global verification_codes
    
    try:
        data = request.get_json()
        user_id = data.get('user_id', '').strip()
        
        if not user_id:
            return jsonify({'success': False, 'message': 'الرجاء إدخال رقم الآيدي'}), 400
        
        # التحقق من أن user_id أرقام فقط
        if not user_id.isdigit():
            return jsonify({'success': False, 'message': 'آيدي غير صحيح - يجب أن يكون أرقام فقط'}), 400
        
        user_id = str(int(user_id))  # تنظيف الـ ID
        
        # التحقق من أن المستخدم موجود في Telegram
        try:
            user = bot.get_chat(int(user_id))
            user_name = user.first_name or "مستخدم"
        except Exception as e:
            return jsonify({'success': False, 'message': f'لم نتمكن من العثور على هذا الآيدي في Telegram'}), 404
        
        # توليد كود عشوائي 6 أرقام
        code = str(random.randint(100000, 999999))
        
        # حفظ الكود في الذاكرة مع الـ timestamp
        # ✅ الكود صالح لـ 2 دقيقة
        verification_codes[user_id] = {
            'code': code,
            'name': user_name,
            'created_at': time.time()
        }
        
        # ✅ إعادة تعيين المحاولات الفاشلة عند طلب كود جديد
        from security_utils import reset_failed_attempts
        reset_failed_attempts(user_id)
        
        # إرسال الكود للمستخدم عبر Telegram
        try:
            message_text = f"""
🔐 كود التحقق من حسابك في المتجر:
<code>{code}</code>

⏰ صالح لمدة 2 دقيقة فقط
3️⃣ محاولات خاطئة = الكود ينتهي
📲 اطلب كود جديد بعد 1 دقيقة

⚠️ لا تشارك هذا الكود مع أحد!
"""
            bot.send_message(int(user_id), message_text, parse_mode='HTML')
            
            return jsonify({
                'success': True, 
                'message': f'✅ تم إرسال كود التحقق إلى Telegram',
                'user_name': user_name
            })
        
        except Exception as e:
            print(f"❌ خطأ في إرسال الرسالة: {e}")
            # يمكن للمستخدم محاولة إدخال الكود حتى لو لم يتم الإرسال
            return jsonify({
                'success': True,
                'message': f'✅ تم توليد الكود (قد لا يكون وصل الرسالة)',
                'user_name': user_name
            })
    
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في السيرفر'}), 500

# � تسجيل الدخول برقم الجوال
@app.route('/api/send_code_by_phone', methods=['POST'])
@limiter.limit("5 per minute")  # 🔒 Rate Limiting
def send_code_by_phone():
    """البحث عن الحساب برقم الجوال وإرسال كود التحقق لـ Telegram"""
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        
        if not phone:
            return jsonify({'success': False, 'message': 'الرجاء إدخال رقم الجوال'}), 400
        
        # تنظيف رقم الجوال
        import re
        phone = phone.replace(' ', '').replace('-', '').replace('+', '')
        
        # تحويل الصيغ المختلفة إلى 05xxxxxxxx
        if phone.startswith('966'):
            phone = '0' + phone[3:]
        elif phone.startswith('5') and len(phone) == 9:
            phone = '0' + phone
        
        # التحقق من صيغة الرقم السعودي
        if not re.match(r'^05\d{8}$', phone):
            return jsonify({'success': False, 'message': 'رقم جوال غير صحيح. يجب أن يبدأ بـ 05 ويتكون من 10 أرقام'}), 400
        
        # البحث عن الحساب المرتبط بهذا الرقم
        users_ref = db.collection('users')
        if USE_FIELD_FILTER:
            query = users_ref.where(filter=FieldFilter('phone', '==', phone)).where(filter=FieldFilter('phone_verified', '==', True)).limit(1)
        else:
            query = users_ref.where('phone', '==', phone).where('phone_verified', '==', True).limit(1)
        results = list(query.stream())
        
        if not results:
            return jsonify({
                'success': False, 
                'message': 'لا يوجد حساب مرتبط بهذا الرقم أو الرقم غير موثق'
            }), 404
        
        user_doc = results[0]
        user_id = user_doc.id
        user_data = user_doc.to_dict()
        user_name = user_data.get('name', user_data.get('first_name', 'مستخدم'))
        
        # توليد كود عشوائي 6 أرقام
        code = str(random.randint(100000, 999999))
        
        # حفظ الكود في الذاكرة
        verification_codes[user_id] = {
            'code': code,
            'name': user_name,
            'created_at': time.time()
        }
        
        # إعادة تعيين المحاولات الفاشلة
        from security_utils import reset_failed_attempts
        reset_failed_attempts(user_id)
        
        # إرسال الكود للمستخدم عبر Telegram
        try:
            message_text = f"""
🔐 كود التحقق للدخول برقم الجوال:
<code>{code}</code>

📱 تم طلب الدخول باستخدام: {phone}

⏰ صالح لمدة 2 دقيقة فقط
3️⃣ محاولات خاطئة = الكود ينتهي

⚠️ إذا لم تطلب هذا، تجاهل الرسالة!
"""
            bot.send_message(int(user_id), message_text, parse_mode='HTML')
            
            return jsonify({
                'success': True, 
                'message': '✅ تم إرسال كود التحقق إلى Telegram',
                'user_id': user_id
            })
        
        except Exception as e:
            print(f"❌ خطأ في إرسال الرسالة: {e}")
            return jsonify({
                'success': False,
                'message': 'فشل إرسال الكود، تأكد من تفعيل البوت'
            }), 500
    
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في السيرفر'}), 500

# مسار التحقق من الكود وتسجيل الدخول
@app.route('/verify', methods=['POST'])
@limiter.limit("10 per minute")  # 🔒 Rate Limiting عام
def verify_login():
    from security_utils import (
        is_code_expired_due_to_wrong_attempts, record_failed_code_attempt,
        reset_failed_attempts, get_remaining_attempts, log_security_event
    )
    
    data = request.get_json()
    user_id = data.get('user_id')
    code = data.get('code')
    
    if not user_id or not code:
        return {'success': False, 'message': 'الرجاء إدخال الآيدي والكود'}, 400
    
    user_id = str(user_id)
    
    # ✅ فحص انتهاء صلاحية الكود بسبب محاولات خاطئة
    if is_code_expired_due_to_wrong_attempts(user_id):
        # حذف الكود من الذاكرة لمنع أي محاولات إضافية
        if user_id in verification_codes:
            del verification_codes[user_id]
        log_security_event('CODE_EXPIRED_TOO_MANY_ATTEMPTS', user_id, 'تم محاولة 3 مرات')
        return {
            'success': False, 
            'message': '❌ الكود انتهى بسبب محاولات خاطئة\n\n📲 الرجاء اطلب كود جديد (بعد 1 دقيقة)',
            'action': 'request_new_code'
        }, 401
    
    # التحقق من صحة الكود
    code_data = verify_code(user_id, code)
    
    if not code_data:
        # ❌ كود خاطئ - تسجيل المحاولة
        action, wait_time = record_failed_code_attempt(user_id)
        remaining = get_remaining_attempts(user_id)[0]
        
        error_msg = f'❌ الكود غير صحيح\n\n🔄 محاولات متبقية: {remaining}/3'
        
        if action == 'code_expired':
            # حذف الكود من الذاكرة عند المحاولة الثالثة الفاشلة
            if user_id in verification_codes:
                del verification_codes[user_id]
            log_security_event('CODE_WRONG_ATTEMPT', user_id, f'محاولة 3/3')
            return {
                'success': False, 
                'message': f'{error_msg}\n\n⏰ انتهت محاولاتك\n📲 اطلب كود جديد (بعد 1 دقيقة)',
                'action': 'request_new_code'
            }, 401
        
        log_security_event('CODE_WRONG_ATTEMPT', user_id, f'محاولة {3-remaining}/3')
        return {'success': False, 'message': error_msg}, 401
    
    # ✅ كود صحيح - إعادة تعيين المحاولات
    reset_failed_attempts(user_id)
    
    # 🔐 التحقق من تفعيل المصادقة الثنائية (2FA)
    try:
        user_doc = db.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data.get('totp_enabled', False):
                # المستخدم مفعّل 2FA - لا نسجل دخوله بعد، نطلب منه كود 2FA
                # نحفظ معلوماته مؤقتاً في الجلسة
                session['pending_2fa_user_id'] = user_id
                session['pending_2fa_user_name'] = code_data['name']
                session['pending_2fa_time'] = time.time()
                # حذف الكود بعد الاستخدام
                del verification_codes[user_id]
                return {
                    'success': True,
                    'requires_2fa': True,
                    'message': '🔐 أدخل كود المصادقة الثنائية'
                }
    except Exception as e:
        print(f"⚠️ خطأ في فحص 2FA: {e}")
    
    # تجديد الجلسة لمنع Session Fixation
    regenerate_session()
    
    # تسجيل دخول المستخدم
    session.permanent = True  # تفعيل انتهاء الصلاحية التلقائي
    session['user_id'] = user_id
    session['user_name'] = code_data['name']
    session['login_time'] = time.time()  # وقت تسجيل الدخول

    # حذف الكود بعد الاستخدام
    if user_id in verification_codes:
        del verification_codes[user_id]

    # جلب الرصيد
    balance = get_balance(user_id)

    # جلب صورة الحساب من تيليجرام أو Firebase
    profile_photo_url = None
    try:
        # أولاً: محاولة جلب من Firebase
        user_doc = db.collection('users').document(user_id).get()
        if user_doc.exists:
            profile_photo_url = user_doc.to_dict().get('profile_photo')
        
        # ثانياً: إذا لم توجد، جلب من تيليجرام مباشرة
        if not profile_photo_url:
            photos = bot.get_user_profile_photos(int(user_id), limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][0].file_id
                file_info = bot.get_file(file_id)
                token = bot.token
                profile_photo_url = f"https://api.telegram.org/file/bot{token}/{file_info.file_path}"
                # حفظ في Firebase للاستخدام لاحقاً
                db.collection('users').document(user_id).update({'profile_photo': profile_photo_url})
    except Exception as e:
        print(f"⚠️ خطأ في جلب صورة الحساب: {e}")
    
    # حفظ في الجلسة
    if profile_photo_url:
        session['profile_photo'] = profile_photo_url

    return {
        'success': True,
        'message': 'تم تسجيل الدخول بنجاح',
        'user_name': code_data['name'],
        'balance': balance,
        'profile_photo_url': profile_photo_url
    }

# 🔐 التحقق من المصادقة الثنائية (2FA) عند تسجيل الدخول
@app.route('/verify_2fa_login', methods=['POST'])
@limiter.limit("10 per minute")
def verify_2fa_login():
    """التحقق من كود المصادقة الثنائية أثناء تسجيل الدخول"""
    import pyotp
    
    data = request.get_json()
    totp_code = data.get('totp_code', '').strip()
    
    # التحقق من وجود بيانات 2FA المؤقتة
    user_id = session.get('pending_2fa_user_id')
    user_name = session.get('pending_2fa_user_name')
    pending_time = session.get('pending_2fa_time', 0)
    
    if not user_id:
        return {'success': False, 'message': '❌ الجلسة منتهية، أعد تسجيل الدخول'}, 401
    
    # التحقق من صلاحية الوقت (5 دقائق)
    if time.time() - pending_time > 300:
        session.pop('pending_2fa_user_id', None)
        session.pop('pending_2fa_user_name', None)
        session.pop('pending_2fa_time', None)
        return {'success': False, 'message': '⏰ انتهت المهلة، أعد تسجيل الدخول'}, 401
    
    if not totp_code or len(totp_code) != 6:
        return {'success': False, 'message': '❌ أدخل كود مكون من 6 أرقام'}, 400
    
    try:
        # جلب secret من Firebase
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return {'success': False, 'message': '❌ المستخدم غير موجود'}, 404
        
        user_data = user_doc.to_dict()
        totp_secret = user_data.get('totp_secret')
        
        if not totp_secret:
            return {'success': False, 'message': '❌ المصادقة الثنائية غير مفعّلة'}, 400
        
        # فك تشفير المفتاح
        totp_secret = decrypt_data(totp_secret)
        
        # التحقق من الكود
        totp = pyotp.TOTP(totp_secret)
        if not totp.verify(totp_code, valid_window=1):
            return {'success': False, 'message': '❌ الكود غير صحيح'}, 401
        
        # ✅ نجاح - تسجيل الدخول الكامل
        session.pop('pending_2fa_user_id', None)
        session.pop('pending_2fa_user_name', None)
        session.pop('pending_2fa_time', None)
        
        regenerate_session()
        session.permanent = True
        session['user_id'] = user_id
        session['user_name'] = user_name
        session['login_time'] = time.time()
        
        # جلب الرصيد والصورة
        balance = get_balance(user_id)
        profile_photo_url = user_data.get('profile_photo')
        
        if profile_photo_url:
            session['profile_photo'] = profile_photo_url
        
        return {
            'success': True,
            'message': '✅ تم تسجيل الدخول بنجاح',
            'user_name': user_name,
            'balance': balance,
            'profile_photo_url': profile_photo_url
        }
        
    except Exception as e:
        print(f"❌ خطأ في التحقق من 2FA: {e}")
        return {'success': False, 'message': '❌ حدث خطأ في السيرفر'}, 500

# --- التحقق من صلاحية الجلسة ---
@app.before_request
def check_session_validity():
    """التحقق من صلاحية الجلسة قبل كل طلب"""
    if 'user_id' in session:
        login_time = session.get('login_time', 0)
        # التحقق من انتهاء الصلاحية (30 دقيقة)
        if time.time() - login_time > 1800:  # 30 * 60 = 1800 ثانية
            session.clear()
            print("⏰ انتهت صلاحية الجلسة")

@app.route('/robots.txt')
def robots_txt():
    """ملف robots.txt للمحركات البحث"""
    return """User-agent: *
Allow: /
Disallow: /admin
Disallow: /webhook
Disallow: /payment/
Disallow: /api/
""", 200, {'Content-Type': 'text/plain'}

@app.route('/favicon.ico')
def favicon():
    """أيقونة الموقع"""
    return '', 204

@app.route('/')
def index():
    """الصفحة الرئيسية - عرض الفئات الافتراضية 3×3"""
    # ✅ جلب معلومات المستخدم (إن وجدت)
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'ضيف')
    profile_photo = session.get('profile_photo', '')
    is_logged_in = bool(user_id)
    
    # 1. جلب الرصيد
    balance = 0.0
    if user_id:
        try:
            user_doc = db.collection('users').document(str(user_id)).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                balance = user_data.get('balance', 0.0)
                if not profile_photo:
                    profile_photo = user_data.get('profile_photo', '')
        except:
            balance = get_balance(user_id)
    
    # 2. جلب الفئات من Firebase أو استخدام الافتراضية 3×3
    categories = []
    try:
        cat_docs = db.collection('categories').stream()
        db_categories = list(cat_docs)
        
        if db_categories:
            # الفئات من قاعدة البيانات
            for doc in db_categories:
                cat = doc.to_dict()
                cat['id'] = doc.id
                categories.append(cat)
            print(f"✅ تم جلب {len(categories)} فئة من Firebase")
        else:
            # الفئات الافتراضية 3×3
            categories = DEFAULT_CATEGORIES
            print(f"✅ استخدام الفئات الافتراضية: {len(categories)} فئة")
    except:
        # الفئات الافتراضية 3×3
        categories = DEFAULT_CATEGORIES
        print(f"✅ استخدام الفئات الافتراضية")
    
    # 3. جلب عدد منتجات السلة
    cart_count = 0
    if user_id:
        cart = get_user_cart(str(user_id)) or {}
        cart_count = len(cart.get('items', []))
    
    # 4. تحضير JSON للفئات للـ JavaScript
    import json
    categories_json = json.dumps([{'id': cat.get('id', ''), 'name': cat.get('name', '')} for cat in categories])
    
    # عرض الصفحة الرئيسية بالفئات 3×3
    return render_template('categories.html',
                         categories=categories,
                         categories_json=categories_json,
                         balance=balance,
                         current_user_id=user_id or 0,
                         current_user=user_id,
                         user_name=user_name,
                         profile_photo=profile_photo,
                         is_logged_in=is_logged_in,
                         cart_count=cart_count,
                         contact_bot_url=CONTACT_BOT_URL,
                         contact_whatsapp=CONTACT_WHATSAPP)


# ====== Web Routes - تم نقلها إلى routes/web_routes.py ======

@app.route('/get_balance')
def get_balance_api():
    # استخدام الجلسة فقط لمنع كشف أرصدة المستخدمين
    user_id = session.get('user_id')
    
    if not user_id:
        return {'balance': 0}
    
    balance = get_balance(user_id)
    return {'balance': balance}

@app.route('/charge_balance', methods=['POST'])
@limiter.limit("5 per minute")  # 🔒 Rate Limiting: منع تخمين مفاتيح الشحن
def charge_balance_api():
    """شحن الرصيد باستخدام كود الشحن"""
    data = request.json
    key_code = data.get('charge_key', '').strip()
    
    # ===== التحقق الآمن من هوية المستخدم =====
    if not session.get('user_id'):
        return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً!'})
    
    user_id = str(session.get('user_id'))
    
    if not key_code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال كود الشحن'})
    
    # البحث عن الكود في Firebase مباشرة
    key_data = get_charge_key(key_code)
    
    # التحقق من وجود الكود
    if not key_data:
        return jsonify({'success': False, 'message': 'كود الشحن غير صحيح أو غير موجود'})
    
    # التحقق من أن الكود لم يستخدم
    if key_data.get('used', False):
        return jsonify({'success': False, 'message': 'هذا الكود تم استخدامه مسبقاً'})
    
    # شحن الرصيد
    amount = key_data.get('amount', 0)
    new_balance = add_balance(user_id, amount)
    
    # تحديث الكود كمستخدم
    use_charge_key(key_code, user_id)
    
    # حفظ سجل الشحنة
    if db:
        try:
            from datetime import datetime
            import time as time_module
            db.collection('charge_history').add({
                'user_id': user_id,
                'amount': amount,
                'key_code': key_code,
                'method': 'key',
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'timestamp': firestore.SERVER_TIMESTAMP,
                'type': 'charge'
            })
            print(f"✅ تم تسجيل شحنة الكود في charge_history: {amount} ريال للمستخدم {user_id}")
            
            # إشعار المالك بالشحن
            notify_new_charge(user_id, amount, method='key')
        except Exception as e:
            print(f"خطأ في حفظ سجل الشحن: {e}")
    
    return jsonify({
        'success': True, 
        'message': f'تم شحن {amount} ريال بنجاح!',
        'new_balance': new_balance
    })

@app.route('/sell', methods=['POST'])
def sell_item():
    data = request.json
    seller_id = str(data.get('seller_id'))
    
    # التحقق من أن البائع هو المالك فقط
    if int(seller_id) != ADMIN_ID:
        return {'status': 'error', 'message': 'غير مصرح لك بإضافة منتجات! فقط المالك يمكنه ذلك.'}
    
    # حفظ البيانات المخفية بشكل آمن
    item = {
        'id': str(uuid.uuid4()),  # رقم فريد لا يتكرر
        'item_name': data.get('item_name'),
        'price': data.get('price'),
        'seller_id': seller_id,
        'seller_name': data.get('seller_name'),
        'hidden_data': data.get('hidden_data', ''),  # البيانات المخفية
        'category': data.get('category', ''),  # الفئة
        'image_url': data.get('image_url', '')  # رابط الصورة
    }
    
    # حفظ في Firebase
    add_product(item)
    
    return {'status': 'success'}

@app.route('/buy', methods=['POST'])
@limiter.limit("10 per minute")  # 🔒 Rate Limiting: منع الشراء الآلي
def buy_item():
    try:
        data = request.json
        item_id = str(data.get('item_id'))  # تأكد أنه نص
        buyer_details = sanitize(data.get('buyer_details', ''))  # ✅ تنظيف XSS

        # ===== التحقق الآمن من هوية المشتري =====
        # لا نثق بـ buyer_id القادم من الطلب!
        # نأخذه فقط من الـ session (بعد تسجيل الدخول)
        
        buyer_id = None
        buyer_name = None
        
        # 1️⃣ التحقق من الجلسة (المستخدم مسجل دخول)
        if session.get('user_id'):
            buyer_id = str(session.get('user_id'))
            buyer_name = session.get('user_name', 'مستخدم')
            print(f"✅ مشتري موثق من الجلسة: {buyer_id}")
        else:
            # 2️⃣ لم يسجل دخول - نرفض الطلب
            print(f"❌ محاولة شراء بدون تسجيل دخول!")
            return {'status': 'error', 'message': 'يجب تسجيل الدخول أولاً!'}
        
        print(f"🛒 محاولة شراء - item_id: {item_id}, buyer_id: {buyer_id}")

        # 1. البحث عن المنتج في Firebase مباشرة
        doc_ref = db.collection('products').document(item_id)
        doc = doc_ref.get()

        if not doc.exists:
            print(f"❌ المنتج {item_id} غير موجود في Firebase")
            return {'status': 'error', 'message': 'المنتج غير موجود أو تم حذفه!'}
        else:
            item = doc.to_dict()
            item['id'] = doc.id
            print(f"✅ تم إيجاد المنتج في Firebase: {item.get('item_name')}")

        # 2. التحقق من أن المنتج لم يُباع
        if item.get('sold', False):
            return {'status': 'error', 'message': 'عذراً، هذا المنتج تم بيعه للتو! 🚫'}

        price = float(item.get('price', 0))

        # 3. التحقق الفعلي من إمكانية إرسال رسالة للمشتري (قبل إتمام الشراء)
        # نرسل رسالة حقيقية لأن chat_action لا تفشل حتى لو المستخدم حظر البوت
        try:
            test_msg = bot.send_message(
                int(buyer_id),
                "🛒",  # رسالة قصيرة جداً
                disable_notification=True  # بدون صوت إشعار
            )
            bot.delete_message(int(buyer_id), test_msg.message_id)
            print(f"✅ تم التحقق من إمكانية إرسال الرسائل للمشتري {buyer_id}")
        except Exception as e:
            print(f"❌ فشل التحقق من المشتري {buyer_id}: {e}")
            # إنشاء رسالة الخطأ مع رابط البوت
            bot_link = f"@{BOT_USERNAME}" if BOT_USERNAME else "البوت"
            error_msg = f'⚠️ لا يمكن إرسال البيانات لك!\n\nتأكد أنك:\n1. لم تحظر البوت {bot_link}\n2. لم تحذف المحادثة معه\n\nأو اذهب للبوت واضغط /start ثم حاول مرة أخرى'
            return {'status': 'error', 'message': error_msg}

        # 4. التحقق من رصيد المشتري (من Firebase مباشرة)
        user_ref = db.collection('users').document(buyer_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return {'status': 'error', 'message': 'حدث خطأ! حاول مرة أخرى.'}
        
        user_data = user_doc.to_dict()
        current_balance = user_data.get('balance', 0.0)

        if current_balance < price:
            return {'status': 'error', 'message': 'رصيدك غير كافي للشراء!'}

        # 4. تنفيذ العملية (خصم + تحديث حالة المنتج)
        # نستخدم batch لضمان تنفيذ كل الخطوات معاً أو فشلها معاً
        batch = db.batch()

        # خصم الرصيد
        new_balance = current_balance - price
        batch.update(user_ref, {'balance': new_balance})

        # تحديث المنتج كمباع (تأكد من استخدام document reference الصحيح)
        product_doc_ref = db.collection('products').document(item_id)
        batch.set(product_doc_ref, {
            'sold': True,
            'buyer_id': buyer_id,
            'buyer_name': buyer_name,
            'sold_at': firestore.SERVER_TIMESTAMP
        }, merge=True)

        # حفظ الطلب
        order_id = f"ORD_{random.randint(100000, 999999)}"
        order_ref = db.collection('orders').document(order_id)
        
        # تحديد نوع التسليم
        delivery_type = item.get('delivery_type', 'instant')
        order_status = 'completed' if delivery_type == 'instant' else 'pending'
        
        batch.set(order_ref, {
            'buyer_id': buyer_id,
            'buyer_name': buyer_name,
            'item_name': item.get('item_name'),
            'price': price,
            'hidden_data': item.get('hidden_data'),
            'buyer_details': buyer_details,  # تفاصيل المشتري للتسليم اليدوي
            'buyer_instructions': item.get('buyer_instructions', ''),  # ما كان مطلوب من المشتري
            'details': item.get('details', ''),
            'category': item.get('category', ''),
            'image_url': item.get('image_url', ''),
            'seller_id': item.get('seller_id'),
            'delivery_type': delivery_type,
            'status': order_status,
            'created_at': firestore.SERVER_TIMESTAMP
        })

        # تنفيذ التغييرات
        try:
            batch.commit()
            print(f"✅ تم حفظ الطلب في Firebase: {order_id} (نوع: {delivery_type})")
        except Exception as batch_error:
            print(f"❌ فشل حفظ الطلب في Firebase: {batch_error}")
            return {'status': 'error', 'message': 'فشل حفظ الطلب! حاول مرة أخرى'}
        
        # التحقق من حفظ الطلب (للتسليم اليدوي فقط)
        if delivery_type == 'manual':
            try:
                verify_order = db.collection('orders').document(order_id).get()
                if verify_order.exists:
                    print(f"✅ تم التحقق من وجود الطلب: {order_id}")
                else:
                    print(f"⚠️ الطلب غير موجود بعد الحفظ: {order_id}")
            except Exception as verify_error:
                print(f"⚠️ فشل التحقق من الطلب: {verify_error}")

        # 5. إرسال المنتج للمشتري أو إشعار الأدمن
        # فك تشفير البيانات السرية قبل الإرسال
        raw_hidden = item.get('hidden_data', '')
        hidden_info = decrypt_data(raw_hidden) if raw_hidden else 'لا توجد بيانات'
        message_sent = False
        
        if delivery_type == 'instant':
            # تسليم فوري - إرسال البيانات مباشرة للمشتري
            try:
                bot.send_message(
                    int(buyer_id),
                    f"✅ تم الشراء بنجاح!\n\n"
                    f"📦 المنتج: {item.get('item_name')}\n"
                    f"💰 السعر: {price} ريال\n"
                    f"🆔 رقم الطلب: #{order_id}\n\n"
                    f"🔐 بيانات الاشتراك:\n{hidden_info}\n\n"
                    f"⚠️ احفظ هذه البيانات في مكان آمن!"
                )
                message_sent = True
                print(f"✅ تم إرسال بيانات المنتج للمشتري {buyer_id}")
                
                # إشعار للمالك
                bot.send_message(
                    ADMIN_ID,
                    f"🔔 عملية بيع جديدة!\n"
                    f"📦 المنتج: {item.get('item_name')}\n"
                    f"👤 المشتري: {buyer_name} ({buyer_id})\n"
                    f"💰 السعر: {price} ريال\n"
                    f"✅ تم إرسال البيانات للمشتري"
                )
            except Exception as e:
                print(f"⚠️ فشل إرسال الرسالة للمشتري {buyer_id}: {e}")
                # إشعار المالك بالفشل
                try:
                    bot.send_message(
                        ADMIN_ID,
                        f"⚠️ تنبيه: فشل إرسال بيانات المنتج!\n"
                        f"📦 المنتج: {item.get('item_name')}\n"
                        f"👤 المشتري: {buyer_name} ({buyer_id})\n"
                        f"🔐 البيانات: {hidden_info}\n"
                        f"❌ السبب: {str(e)}"
                    )
                except:
                    pass
        else:
            # تسليم يدوي - إشعار المشتري بانتظار التنفيذ وإرسال للأدمنز
            try:
                bot.send_message(
                    int(buyer_id),
                    f"⏳ تم استلام طلبك!\n\n"
                    f"📦 المنتج: {item.get('item_name')}\n"
                    f"💰 السعر: {price} ريال\n"
                    f"🆔 رقم الطلب: #{order_id}\n\n"
                    f"👨‍💼 طلبك بانتظار التنفيذ من قبل الإدارة\n"
                    f"📲 سيتم إرسال البيانات لك فور تنفيذ الطلب"
                )
                message_sent = True
                print(f"✅ تم إشعار المشتري {buyer_id} بانتظار التنفيذ")
            except Exception as e:
                print(f"⚠️ فشل إرسال رسالة الانتظار للمشتري {buyer_id}: {e}")
            
            # إرسال إشعار لجميع الأدمنز مع زر التنفيذ
            claim_markup = telebot.types.InlineKeyboardMarkup()
            claim_markup.add(telebot.types.InlineKeyboardButton(
                "📋 استلام الطلب", 
                callback_data=f"claim_order_{order_id}"
            ))
            
            # 🔒 إخفاء بيانات المشتري في الإشعار الأولي للحماية
            # البيانات تظهر فقط للمشرف الذي يستلم الطلب
            hidden_buyer_details = ""
            if buyer_details:
                hidden_buyer_details = f"\n\n📝 بيانات المشتري: 🔒 ******** (تظهر عند الاستلام)"
            
            admin_message = (
                f"🆕 طلب جديد بانتظار التنفيذ!\n\n"
                f"🆔 رقم الطلب: #{order_id}\n"
                f"📦 المنتج: {item.get('item_name')}\n"
                f"👤 المشتري: {buyer_name}\n"
                f"💰 السعر: {price} ريال"
                f"{hidden_buyer_details}\n\n"
                f"👇 اضغط لاستلام وعرض التفاصيل"
            )
            
            # إرسال للمالك الرئيسي
            try:
                bot.send_message(ADMIN_ID, admin_message, reply_markup=claim_markup)
            except:
                pass
            


        # إرجاع البيانات للموقع
        # ⚠️ إصلاح أمني: لا نرسل hidden_data في الـ response
        # البيانات تُرسل فقط عبر Telegram والإيميل للأمان

        # إرسال بيانات الطلب بالإيميل (إذا مربوط ومفعّل)
        buyer_email = user_data.get('email', '')
        if buyer_email and user_data.get('email_verified', False):
            email_item = {
                'name': item.get('item_name', ''),
                'price': price,
                'order_id': order_id,
                'delivery_type': delivery_type
            }
            if delivery_type == 'instant' and raw_hidden:
                email_item['hidden_data'] = hidden_info
            send_order_email(buyer_email, [email_item], price, new_balance)

        return {
            'status': 'success',
            'order_id': order_id,
            'message_sent': message_sent,
            'new_balance': new_balance,
            'delivery_type': delivery_type,
            'message': 'تم الشراء بنجاح! تم إرسال البيانات لك عبر Telegram' if delivery_type == 'instant' else 'تم استلام طلبك وسيتم تنفيذه قريباً'
        }

    except Exception as e:
        print(f"❌ Error in buy_item: {e}")
        return {'status': 'error', 'message': 'حدث خطأ أثناء الشراء، حاول مرة أخرى.'}

# ============================================
# === نقاط استقبال بوابة الدفع EdfaPay ===
# ============================================

# Webhook الديناميكي لـ EdfaPay (يستخدم merchant_id في الرابط)
@app.route('/merchant_webhook/<merchant_id>', methods=['GET', 'POST'])
def merchant_webhook(merchant_id):
    """استقبال إشعارات الدفع من EdfaPay على الرابط الديناميكي"""
    # تجاهل رسائل Telegram (تحتوي على update_id)
    if request.method == 'POST':
        data = request.json or request.form.to_dict()
        if data.get('update_id') or data.get('message'):
            # هذه رسالة من Telegram وليست من EdfaPay
            print(f"⚠️ تم تجاهل رسالة Telegram على merchant_webhook")
            return jsonify({'status': 'ok', 'message': 'Telegram message ignored'}), 200
    return process_edfapay_callback(request, f"merchant_webhook/{merchant_id}")

# دعم كلا الصيغتين: edfapay_webhook و edfapay-webhook
@app.route('/payment/edfapay_webhook', methods=['GET', 'POST'])
@app.route('/payment/edfapay-webhook', methods=['GET', 'POST'])
@limiter.limit("30 per minute")  # 🔒 Rate Limiting: منع هجمات الـ webhook
def edfapay_webhook():
    """استقبال إشعارات الدفع من EdfaPay"""
    return process_edfapay_callback(request, "edfapay_webhook")

def process_edfapay_callback(req, source):
    """معالجة callback من EdfaPay"""
    
    # إذا كان الطلب GET (فتح من المتصفح) - عرض رسالة
    if req.method == 'GET':
        return jsonify({
            'status': 'ok',
            'message': 'EdfaPay Webhook Endpoint',
            'description': 'This endpoint receives payment notifications from EdfaPay',
            'source': source,
            'method': 'POST only'
        })
    
    try:
        # جلب البيانات (تدعم JSON و form-data)
        data = {}
        if req.is_json:
            data = req.json or {}
        else:
            data = req.form.to_dict() or {}
        
        # إذا كانت البيانات فارغة، جرب query parameters
        if not data:
            data = req.args.to_dict() or {}
        
        print(f"📩 EdfaPay Webhook ({source}): {data}")
        
        # ===== 🔐 التحقق من صحة الطلب (Signature Verification) =====
        order_id = data.get('order_id', '')
        trans_id = data.get('trans_id', '')
        status = data.get('status', '') or data.get('result', '')
        amount = data.get('order_amount', '') or data.get('amount', '') or data.get('trans_amount', '')
        received_hash = data.get('hash', '')
        
        # التحقق من أن الطلب من EdfaPay وليس مزيف
        if order_id and EDFAPAY_PASSWORD:
            # 1️⃣ التحقق من وجود الطلب في النظام أولاً
            payment_exists = order_id in pending_payments
            if not payment_exists:
                try:
                    doc = db.collection('pending_payments').document(order_id).get()
                    payment_exists = doc.exists
                except:
                    pass
            
            if not payment_exists:
                print(f"🚫 محاولة webhook مزيفة! order_id غير موجود: {order_id}")
                # إرسال تنبيه أمني للمالك
                try:
                    if BOT_ACTIVE:
                        client_ip = req.headers.get('X-Forwarded-For', req.remote_addr)
                        alert_msg = f"""
⚠️ *تنبيه أمني - Webhook مشبوه!*

🔴 محاولة إرسال webhook لطلب غير موجود!

📋 Order ID: `{order_id}`
💰 المبلغ المزعوم: {amount}
🌐 IP: `{client_ip}`
⏰ الوقت: {time.strftime('%Y-%m-%d %H:%M:%S')}

_قد تكون محاولة اختراق!_
                        """
                        bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
                except:
                    pass
                return jsonify({'status': 'error', 'message': 'Invalid order'}), 403
            
            # 2️⃣ التحقق من أن المبلغ المرسل يطابق المبلغ الأصلي
            original_payment = pending_payments.get(order_id)
            if not original_payment:
                try:
                    doc = db.collection('pending_payments').document(order_id).get()
                    if doc.exists:
                        original_payment = doc.to_dict()
                except:
                    pass
            
            if original_payment and amount:
                original_amount = float(original_payment.get('amount', 0))
                received_amount = float(amount) if amount else 0
                
                if original_amount != received_amount:
                    print(f"🚫 محاولة تزوير المبلغ! الأصلي: {original_amount}, المستلم: {received_amount}")
                    try:
                        if BOT_ACTIVE:
                            client_ip = req.headers.get('X-Forwarded-For', req.remote_addr)
                            alert_msg = f"""
⚠️ *تنبيه أمني - تزوير مبلغ!*

🔴 المبلغ المرسل لا يطابق المبلغ الأصلي!

📋 Order ID: `{order_id}`
💰 المبلغ الأصلي: {original_amount} ريال
💰 المبلغ المزيف: {received_amount} ريال
🌐 IP: `{client_ip}`

_محاولة اختراق واضحة!_
                            """
                            bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
                    except:
                        pass
                    return jsonify({'status': 'error', 'message': 'Amount mismatch'}), 403
            
            # 3️⃣ 🔐 التحقق من صحة الـ Hash (Signature Verification)
            if received_hash and original_payment:
                # حساب الـ Hash المتوقع بنفس طريقة EdfaPay
                # EdfaPay ترسل hash = SHA1(MD5(order_id + order_amount + currency + status + trans_id + password))
                order_desc = original_payment.get('description', f"Recharge {int(original_amount)} SAR")
                
                # محاولة التحقق بعدة صيغ (لأن EdfaPay قد تستخدم صيغ مختلفة)
                hash_verified = False
                
                # صيغة 1: order_id + amount + SAR + description + password
                try:
                    to_hash_1 = f"{order_id}{int(original_amount)}SAR{order_desc}{EDFAPAY_PASSWORD}".upper()
                    expected_hash_1 = hashlib.sha1(hashlib.md5(to_hash_1.encode()).hexdigest().encode()).hexdigest()
                    if received_hash.lower() == expected_hash_1.lower():
                        hash_verified = True
                except:
                    pass
                
                # صيغة 2: reverse order (بعض البوابات تستخدم ترتيب مختلف)
                if not hash_verified:
                    try:
                        to_hash_2 = f"{EDFAPAY_PASSWORD}{order_id}{int(original_amount)}SAR".upper()
                        expected_hash_2 = hashlib.sha1(hashlib.md5(to_hash_2.encode()).hexdigest().encode()).hexdigest()
                        if received_hash.lower() == expected_hash_2.lower():
                            hash_verified = True
                    except:
                        pass
                
                # صيغة 3: مع trans_id و status
                if not hash_verified:
                    try:
                        to_hash_3 = f"{order_id}{int(original_amount)}SAR{trans_id}{status}{EDFAPAY_PASSWORD}".upper()
                        expected_hash_3 = hashlib.sha1(hashlib.md5(to_hash_3.encode()).hexdigest().encode()).hexdigest()
                        if received_hash.lower() == expected_hash_3.lower():
                            hash_verified = True
                    except:
                        pass
                
                # إذا لم يتطابق الـ Hash - رفض الطلب
                if not hash_verified:
                    print(f"🚫 Hash لم يتطابق - received: {received_hash[:20]}... - رفض الطلب!")
                    try:
                        db.collection('security_logs').add({
                            'type': 'webhook_hash_mismatch',
                            'order_id': order_id,
                            'received_hash': received_hash,
                            'ip': req.headers.get('X-Forwarded-For', req.remote_addr),
                            'timestamp': time.time(),
                            'data': str(data)[:500]
                        })
                    except:
                        pass
                    try:
                        if BOT_ACTIVE:
                            client_ip = req.headers.get('X-Forwarded-For', req.remote_addr)
                            bot.send_message(ADMIN_ID, f"⚠️ *تنبيه أمني - Hash غير صحيح!*\n\n📋 Order: `{order_id}`\n🌐 IP: `{client_ip}`", parse_mode='Markdown')
                    except:
                        pass
                    return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
                else:
                    print(f"✅ Hash تم التحقق منه بنجاح")
        
        print(f"📋 Parsed: order_id={order_id}, trans_id={trans_id}, status={status}, amount={amount}")
        
        # التحقق من وجود order_id
        if not order_id:
            print("⚠️ EdfaPay Webhook: لا يوجد order_id - قد يكون إشعار أولي")
            return jsonify({'status': 'ok', 'message': 'No order_id provided'}), 200
        
        # ===== تحديد حالة الدفع =====
        status_upper = str(status).upper().strip()
        
        # الحالات الناجحة
        SUCCESS_STATUSES = ['SUCCESS', 'SETTLED', 'CAPTURED', 'APPROVED', '3DS_SUCCESS']
        
        # الحالات المرفوضة/الفاشلة
        FAILED_STATUSES = ['DECLINED', 'FAILURE', 'FAILED', 'TXN_FAILURE', 'REJECTED', 'CANCELLED', 'ERROR', '3DS_FAILURE']
        
        # الحالات المعلقة (تحتاج انتظار)
        PENDING_STATUSES = ['PENDING', 'PROCESSING', 'REDIRECT', '3DS_REQUIRED']
        
        # ===== معالجة الحالات =====
        
        # 1️⃣ حالة النجاح
        if status_upper in SUCCESS_STATUSES:
            print(f"✅ EdfaPay: عملية ناجحة - {status}")
            
            # البحث عن الطلب في الذاكرة
            payment_data = pending_payments.get(order_id)
            
            # البحث في Firebase إذا لم يوجد في الذاكرة
            if not payment_data:
                try:
                    doc = db.collection('pending_payments').document(order_id).get()
                    if doc.exists:
                        payment_data = doc.to_dict()
                        print(f"📥 تم جلب الطلب من Firebase")
                except Exception as e:
                    print(f"⚠️ خطأ في البحث في Firebase: {e}")
            
            # التحقق من أن الطلب لم يُعالج مسبقاً (حماية من Replay Attack)
            if payment_data and payment_data.get('status') == 'completed':
                print(f"⚠️ محاولة إعادة استخدام webhook! الطلب {order_id} تم معالجته مسبقاً")
                return jsonify({'status': 'ok', 'message': 'Already processed'}), 200
            
            if payment_data and payment_data.get('status') != 'completed':
                user_id = str(payment_data.get('user_id', ''))
                pay_amount = float(payment_data.get('amount', amount or 0))
                is_merchant_invoice = payment_data.get('is_merchant_invoice', False)
                invoice_id = payment_data.get('invoice_id', '')
                
                if not user_id:
                    print(f"❌ لا يوجد user_id في الطلب")
                    return jsonify({'status': 'error', 'message': 'Missing user_id'}), 400
                
                # ✅ إضافة الرصيد
                add_balance(user_id, pay_amount)
                print(f"✅ تم إضافة {pay_amount} ريال للمستخدم {user_id}")
                
                # ✅ إشعار المالك بالشحن
                notify_new_charge(user_id, pay_amount, method='edfapay')
                
                # ✅ تسجيل في سجل الشحنات للسحب
                try:
                    db.collection('charge_history').add({
                        'user_id': user_id,
                        'amount': pay_amount,
                        'method': 'edfapay',
                        'order_id': order_id,
                        'timestamp': time.time(),
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'type': 'payment'
                    })
                    print(f"✅ تم تسجيل الشحنة في charge_history")
                except Exception as e:
                    print(f"⚠️ خطأ في تسجيل charge_history: {e}")
                
                # تحديث في الذاكرة
                if order_id in pending_payments:
                    pending_payments[order_id]['status'] = 'completed'
                
                # تحديث في Firebase
                try:
                    db.collection('pending_payments').document(order_id).update({
                        'status': 'completed',
                        'completed_at': firestore.SERVER_TIMESTAMP,
                        'trans_id': trans_id,
                        'edfapay_status': status,
                        'payment_data': data
                    })
                except Exception as e:
                    print(f"⚠️ خطأ في تحديث Firebase: {e}")
                
                # ===== إشعارات مختلفة حسب نوع الدفع =====
                
                if is_merchant_invoice and invoice_id:
                    # 🔹 فاتورة تاجر - إشعار التاجر
                    try:
                        # تحديث حالة الفاتورة
                        if invoice_id in merchant_invoices:
                            merchant_invoices[invoice_id]['status'] = 'completed'
                        
                        db.collection('merchant_invoices').document(invoice_id).update({
                            'status': 'completed',
                            'completed_at': firestore.SERVER_TIMESTAMP
                        })
                    except:
                        pass
                    
                    # إشعار التاجر
                    try:
                        new_balance = get_balance(user_id)
                        # جلب رقم العميل للمالك فقط
                        customer_phone = ''
                        if invoice_id:
                            if invoice_id in merchant_invoices:
                                customer_phone = merchant_invoices[invoice_id].get('customer_phone', '')
                            if not customer_phone:
                                try:
                                    inv_doc = db.collection('merchant_invoices').document(invoice_id).get()
                                    if inv_doc.exists:
                                        customer_phone = inv_doc.to_dict().get('customer_phone', '')
                                except:
                                    pass
                        if not customer_phone:
                            customer_phone = 'غير محدد'
                        
                        # رسالة للتاجر (بدون رقم العميل)
                        bot.send_message(
                            int(user_id),
                            f"💰 *تم استلام دفعة جديدة!*\n\n"
                            f"🧾 رقم الفاتورة: `{invoice_id}`\n"
                            f"💵 المبلغ: {pay_amount} ريال\n\n"
                            f"💳 رصيدك الحالي: {new_balance} ريال\n\n"
                            f"✅ تم إضافة المبلغ لرصيدك",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"⚠️ خطأ في إرسال إشعار للتاجر: {e}")
                    
                    # إشعار المالك (مفصّل للحماية والتوثيق)
                    try:
                        merchant_name = merchant_invoices.get(invoice_id, {}).get('merchant_name', 'غير معروف')
                        notify_payment_success(
                            user_id=user_id,
                            amount=pay_amount,
                            order_id=order_id,
                            trans_id=trans_id,
                            payment_type='فاتورة تاجر',
                            username=merchant_name,
                            invoice_id=invoice_id,
                            customer_phone=customer_phone,
                            new_balance=new_balance
                        )
                    except:
                        pass
                else:
                    # 🔹 شحن عادي - إشعار المستخدم
                    try:
                        new_balance = get_balance(user_id)
                        bot.send_message(
                            int(user_id),
                            f"✅ *تم شحن رصيدك بنجاح!*\n\n"
                            f"💰 المبلغ المضاف: {pay_amount} ريال\n"
                            f"💵 رصيدك الحالي: {new_balance} ريال\n\n"
                            f"📋 رقم العملية: `{order_id}`\n\n"
                            f"🎉 استمتع بالتسوق!",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"⚠️ خطأ في إرسال إشعار: {e}")
                    
                    # إشعار المالك
                    try:
                        notify_payment_success(
                            user_id=user_id,
                            amount=pay_amount,
                            order_id=order_id,
                            trans_id=trans_id,
                            payment_type='شحن رصيد',
                            new_balance=new_balance
                        )
                    except:
                        pass
                
                return jsonify({'status': 'success', 'message': 'Payment processed'})
            
            elif payment_data and payment_data.get('status') == 'completed':
                print(f"⚠️ الطلب {order_id} تم معالجته مسبقاً")
                return jsonify({'status': 'success', 'message': 'Already processed'})
            
            else:
                print(f"❌ الطلب {order_id} غير موجود")
                return jsonify({'status': 'error', 'message': 'Order not found'}), 404
        
        # 2️⃣ حالة الفشل/الرفض
        elif status_upper in FAILED_STATUSES:
            print(f"❌ EdfaPay: عملية مرفوضة - {status}")
            
            # البحث عن بيانات الطلب لإرسال إشعار للعميل
            payment_data = pending_payments.get(order_id)
            if not payment_data:
                try:
                    doc = db.collection('pending_payments').document(order_id).get()
                    if doc.exists:
                        payment_data = doc.to_dict()
                except:
                    pass
            
            # تحديث حالة الطلب
            try:
                db.collection('pending_payments').document(order_id).update({
                    'status': 'failed',
                    'failed_at': firestore.SERVER_TIMESTAMP,
                    'failure_reason': data.get('decline_reason', status),
                    'payment_data': data
                })
            except:
                pass
            
            # ✅ إشعار العميل بالفشل
            if payment_data:
                try:
                    user_id = payment_data.get('user_id')
                    pay_amount = payment_data.get('amount', 0)
                    is_merchant_invoice = payment_data.get('is_merchant_invoice', False)
                    
                    # تنظيف سبب الرفض من الأحرف الخاصة
                    decline_reason = data.get('decline_reason', 'فشلت العملية')
                    # إزالة الأحرف التي تسبب مشاكل في Markdown
                    decline_reason = decline_reason.replace('_', ' ').replace('*', '').replace('`', '').replace('[', '').replace(']', '')
                    # اختصار الرسالة إذا كانت طويلة
                    if len(decline_reason) > 50:
                        decline_reason = 'تم رفض البطاقة'
                    
                    # رسالة مختلفة حسب نوع الدفع
                    if is_merchant_invoice:
                        msg_text = f"❌ فشلت عملية الدفع\n\n💰 المبلغ: {pay_amount} ريال\n❗ السبب: {decline_reason}\n\n💡 أخبر العميل بالمحاولة مرة أخرى"
                    else:
                        msg_text = f"❌ فشلت عملية الشحن\n\n💰 المبلغ: {pay_amount} ريال\n❗ السبب: {decline_reason}\n\n💡 تأكد من رصيد البطاقة أو جرب بطاقة أخرى"
                    
                    bot.send_message(int(user_id), msg_text)
                except Exception as e:
                    print(f"⚠️ خطأ في إرسال إشعار للعميل: {e}")
            
            # إشعار المالك بالفشل
            try:
                raw_reason = data.get('decline_reason', status)
                
                # جلب بيانات إضافية للمالك
                merchant_id = payment_data.get('user_id', 'غير محدد') if payment_data else 'غير محدد'
                invoice_id = payment_data.get('invoice_id', '') if payment_data else ''
                is_merchant_inv = payment_data.get('is_merchant_invoice', False) if payment_data else False
                
                # جلب رقم العميل إن وجد
                customer_phone = 'غير محدد'
                if invoice_id and invoice_id in merchant_invoices:
                    customer_phone = merchant_invoices[invoice_id].get('customer_phone', 'غير محدد')
                
                # جلب اسم التاجر
                merchant_name = ''
                if invoice_id and invoice_id in merchant_invoices:
                    merchant_name = merchant_invoices[invoice_id].get('merchant_name', '')
                
                if is_merchant_inv:
                    notify_payment_failed(
                        user_id=merchant_id,
                        amount=payment_data.get('amount', 0) if payment_data else 0,
                        order_id=order_id,
                        reason=raw_reason,
                        payment_type='فاتورة تاجر',
                        username=merchant_name,
                        invoice_id=invoice_id,
                        customer_phone=customer_phone
                    )
                else:
                    notify_payment_failed(
                        user_id=merchant_id,
                        amount=payment_data.get('amount', 0) if payment_data else 0,
                        order_id=order_id,
                        reason=raw_reason,
                        payment_type='شحن رصيد'
                    )
            except:
                pass
            
            return jsonify({'status': 'success', 'message': f'Payment failed: {status}'})
        
        # 3️⃣ حالة معلقة
        elif status_upper in PENDING_STATUSES:
            print(f"⏳ EdfaPay: عملية معلقة - {status}")
            
            # إشعار المالك بالعملية المعلقة
            try:
                payment_data = pending_payments.get(order_id)
                if not payment_data:
                    try:
                        doc = db.collection('pending_payments').document(order_id).get()
                        if doc.exists:
                            payment_data = doc.to_dict()
                    except:
                        pass
                
                if payment_data:
                    user_id = payment_data.get('user_id', '')
                    pay_amount = payment_data.get('amount', 0)
                    is_merchant_invoice = payment_data.get('is_merchant_invoice', False)
                    invoice_id = payment_data.get('invoice_id', '')
                    
                    # جلب بيانات إضافية
                    customer_phone = 'غير محدد'
                    merchant_name = ''
                    if invoice_id and invoice_id in merchant_invoices:
                        customer_phone = merchant_invoices[invoice_id].get('customer_phone', 'غير محدد')
                        merchant_name = merchant_invoices[invoice_id].get('merchant_name', '')
                    
                    notify_payment_pending(
                        user_id=user_id,
                        amount=pay_amount,
                        order_id=order_id,
                        payment_type='فاتورة تاجر' if is_merchant_invoice else 'شحن رصيد',
                        username=merchant_name if is_merchant_invoice else None,
                        invoice_id=invoice_id,
                        customer_phone=customer_phone if is_merchant_invoice else None
                    )
            except:
                pass
            
            return jsonify({'status': 'success', 'message': f'Payment pending: {status}'})
        
        # 4️⃣ حالة غير معروفة
        else:
            print(f"❓ EdfaPay: حالة غير معروفة - {status}")
            # لا نضيف رصيد لحالات غير معروفة
            return jsonify({'status': 'success', 'message': f'Unknown status: {status}'})
            
    except Exception as e:
        print(f"❌ خطأ في معالجة webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# لاستقبال تحديثات تيليجرام (Webhook)
@app.route('/webhook', methods=['POST'])
def getMessage():
    try:
        json_string = request.get_data().decode('utf-8')
        print(f"📩 Webhook received: {json_string[:200]}...")
        print(f"🤖 BOT_ACTIVE: {BOT_ACTIVE}")
        
        update = telebot.types.Update.de_json(json_string)
        
        # طباعة تفاصيل التحديث
        if update.message:
            print(f"📝 رسالة نصية من: {update.message.from_user.id}")
            print(f"📝 النص: {update.message.text}")
        
        # ✅ معالجة ضغطات الأزرار (callback_query)
        if update.callback_query:
            print(f"🔘 ضغط زر من: {update.callback_query.from_user.id}")
            print(f"🔘 البيانات: {update.callback_query.data}")
        
        if BOT_ACTIVE:
            print(f"🔢 معالجات الرسائل: {len(bot.message_handlers)}")
            print(f"🔢 معالجات الأزرار: {len(bot.callback_query_handlers)}")
            
            bot.threaded = False
            
            try:
                bot.process_new_updates([update])
                print("✅ تم معالجة التحديث بنجاح")
            except Exception as proc_error:
                print(f"❌ خطأ في المعالجة: {proc_error}")
                import traceback
                traceback.print_exc()
        else:
            print("⚠️ البوت غير نشط!")
    except Exception as e:
        print(f"❌ خطأ في Webhook: {e}")
        import traceback
        traceback.print_exc()
    return "!", 200

@app.route("/set_webhook")
def set_webhook():
    webhook_url = SITE_URL + "/webhook"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return f"Webhook set to {webhook_url}", 200

# Health check endpoint for Render
@app.route('/health')
def health():
    return {'status': 'ok'}, 200

# Service Worker - يجب تقديمه من الجذر لتغطية كل الصفحات
@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/customer-sw.js')
def serve_customer_sw():
    return send_from_directory('static', 'customer-sw.js', mimetype='application/javascript')

@app.route('/customer-manifest.json')
def serve_customer_manifest():
    return send_from_directory('static', 'customer-manifest.json', mimetype='application/manifest+json')

# صفحة تسجيل الدخول للوحة التحكم (HTML منفصل) - نظام الكود المؤقت

# لوحة التحكم للمالك (محدثة بنظام الكود المؤقت) - نسخة محسنة مع Sidebar
@app.route('/dashboard', methods=['GET'])
def dashboard():
    # إذا لم يكن مسجل دخول -> عرض صفحة الدخول بنظام الكود
    if not session.get('is_admin'):
        return render_template('login.html')
    
    # المستخدم مسجل دخول -> عرض لوحة التحكم الجديدة
    return render_template('admin_dashboard.html', active_page='dashboard')

# --- API لإضافة منتج (مصحح للحفظ في Firebase) ---
@app.route('/api/add_product', methods=['POST'])
def api_add_product():
    # ===== التحقق من صلاحية الأدمن =====
    if not session.get('is_admin'):
        return {'status': 'error', 'message': 'غير مصرح!'}
    
    try:
        data = request.json
        name = data.get('name')
        price = data.get('price')
        category = data.get('category')
        details = data.get('details', '')
        image = data.get('image', '')
        hidden_data = data.get('hidden_data')
        
        # التحقق من البيانات
        if not name or not price or not hidden_data:
            return {'status': 'error', 'message': 'بيانات غير كاملة'}
        
        # تشفير البيانات السرية قبل الحفظ
        encrypted_hidden_data = encrypt_data(hidden_data)
        
        # إنشاء بيانات المنتج
        new_id = str(uuid.uuid4())
        item = {
            'id': new_id,
            'item_name': name,
            'price': float(price),
            'seller_id': str(ADMIN_ID),
            'seller_name': 'المالك',
            'hidden_data': encrypted_hidden_data,
            'category': category,
            'details': details,
            'image_url': image,
            'sold': False,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        
        # الحفظ في Firebase
        db.collection('products').document(new_id).set(item)
        print(f"✅ تم حفظ المنتج {new_id} في Firestore: {name}")
        
        # إشعار المالك (داخل try/except لضمان عدم توقف العملية)
        try:
            bot.send_message(
                ADMIN_ID,
                f"✅ **تم إضافة منتج جديد**\n📦 {name}\n💰 {price} ريال",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"فشل إرسال الإشعار: {e}")
            
        return {'status': 'success', 'message': 'تم الحفظ في قاعدة البيانات'}

    except Exception as e:
        print(f"Error in add_product: {e}")
        return {'status': 'error', 'message': f'حدث خطأ في السيرفر: {str(e)}'}

# --- API لتوليد المفاتيح (مصحح للحفظ في Firebase) ---
@app.route('/api/generate_keys', methods=['POST'])
def api_generate_keys():
    # ===== التحقق من صلاحية الأدمن =====
    if not session.get('is_admin'):
        return {'status': 'error', 'message': 'غير مصرح!'}
    
    try:
        data = request.json
        amount = float(data.get('amount'))
        count = int(data.get('count', 1))
        
        if amount <= 0 or count <= 0 or count > 100:
            return {'status': 'error', 'message': 'أرقام غير صحيحة'}
        
        generated_keys = []
        batch = db.batch() # استخدام الدفعات للحفظ السريع
        
        for _ in range(count):
            # إنشاء كود عشوائي
            key_code = f"KEY-{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"
            
            key_data = {
                'amount': amount,
                'used': False,
                'used_by': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            # تجهيز الحفظ في Firebase
            doc_ref = db.collection('charge_keys').document(key_code)
            batch.set(doc_ref, key_data)
            
            generated_keys.append(key_code)
            
        # تنفيذ الحفظ في Firebase دفعة واحدة
        batch.commit()
        
        return {'status': 'success', 'keys': generated_keys}

    except Exception as e:
        print(f"Error generating keys: {e}")
        return {'status': 'error', 'message': f'فشل التوليد: {str(e)}'}

@app.route('/logout_admin')
def logout_admin():
    session.pop('is_admin', None)
    return redirect('/dashboard')

# ==================== صفحة إدارة المنتجات للمالك ====================


# صفحة إدارة الأقسام (للمالك فقط)

# صفحة إدارة المنتجات (للمالك فقط)
@app.route('/admin/products')
def admin_products():
    # التحقق من تسجيل الدخول كمالك
    if not session.get('is_admin'):
        return redirect('/dashboard')
    
    return render_template('admin_products.html', admin_id=ADMIN_ID)

# صفحة إدارة الأقسام (للمالك فقط)
@app.route('/admin/categories')
def admin_categories():
    # التحقق من تسجيل الدخول كمالك
    if not session.get('is_admin'):
        return redirect('/dashboard')
    
    return render_template('admin_categories.html')

# ============ صفحة الفواتير والمعاملات ============
@app.route('/admin/invoices')
def admin_invoices():
    """صفحة عرض جميع الفواتير والمعاملات المالية"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    
    return render_template('admin_invoices.html')

# API لجلب جميع الفواتير والمعاملات
@app.route('/api/admin/get_invoices')
def api_get_invoices():
    """جلب جميع الفواتير والمعاملات المالية"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        # 1️⃣ طلبات الدفع (pending_payments) - شحن الرصيد
        pending_payments_list = []
        try:
            pending_ref = db.collection('pending_payments').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in pending_ref.stream():
                data = doc.to_dict()
                # جلب اسم المستخدم
                user_name = 'غير معروف'
                user_id = data.get('user_id', '')
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                except:
                    pass
                
                pending_payments_list.append({
                    'id': doc.id,
                    'order_id': data.get('order_id', doc.id),
                    'user_id': user_id,
                    'user_name': user_name,
                    'amount': data.get('amount', 0),
                    'status': data.get('status', 'pending'),
                    'type': 'فاتورة تاجر' if data.get('is_merchant_invoice') else 'شحن رصيد',
                    'is_merchant_invoice': data.get('is_merchant_invoice', False),
                    'invoice_id': data.get('invoice_id', ''),
                    'trans_id': data.get('trans_id', ''),
                    'created_at': str(data.get('created_at', '')),
                    'completed_at': str(data.get('completed_at', ''))
                })
        except Exception as e:
            print(f"⚠️ خطأ في جلب pending_payments: {e}")
        
        # 2️⃣ فواتير التجار (merchant_invoices)
        merchant_invoices_list = []
        try:
            invoices_ref = db.collection('merchant_invoices').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in invoices_ref.stream():
                data = doc.to_dict()
                merchant_invoices_list.append({
                    'id': doc.id,
                    'merchant_id': data.get('merchant_id', ''),
                    'merchant_name': data.get('merchant_name', 'تاجر'),
                    'customer_phone': data.get('customer_phone', ''),
                    'amount': data.get('amount', 0),
                    'status': data.get('status', 'pending'),
                    'type': 'فاتورة تاجر',
                    'created_at': str(data.get('created_at', '')),
                    'completed_at': str(data.get('completed_at', ''))
                })
        except Exception as e:
            print(f"⚠️ خطأ في جلب merchant_invoices: {e}")
        
        # 3️⃣ سجل الشحن (charge_history)
        charge_history_list = []
        try:
            charge_ref = db.collection('charge_history').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in charge_ref.stream():
                data = doc.to_dict()
                # جلب اسم المستخدم
                user_name = 'غير معروف'
                user_id = data.get('user_id', '')
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                except:
                    pass
                
                charge_history_list.append({
                    'id': doc.id,
                    'user_id': user_id,
                    'user_name': user_name,
                    'amount': data.get('amount', 0),
                    'method': data.get('method', 'key'),
                    'key_code': data.get('key_code', ''),
                    'type': 'شحن بمفتاح' if data.get('method') == 'key' else 'شحن إلكتروني',
                    'created_at': str(data.get('created_at', ''))
                })
        except Exception as e:
            print(f"⚠️ خطأ في جلب charge_history: {e}")
        
        # 4️⃣ الطلبات/المشتريات (orders)
        orders_list = []
        try:
            orders_ref = db.collection('orders').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in orders_ref.stream():
                data = doc.to_dict()
                orders_list.append({
                    'id': doc.id,
                    'order_id': doc.id[:8],
                    'item_name': data.get('item_name', 'منتج'),
                    'price': data.get('price', 0),
                    'buyer_id': data.get('buyer_id', ''),
                    'buyer_name': data.get('buyer_name', 'مشتري'),
                    'seller_id': data.get('seller_id', ''),
                    'seller_name': data.get('seller_name', 'بائع'),
                    'status': data.get('status', 'completed'),
                    'delivery_type': data.get('delivery_type', 'instant'),
                    'type': 'شراء من الموقع',
                    'created_at': str(data.get('created_at', ''))
                })
        except Exception as e:
            print(f"⚠️ خطأ في جلب orders: {e}")
        
        # 5️⃣ المنتجات المباعة
        sold_products_list = []
        available_products_list = []
        try:
            products_ref = db.collection('products')
            for doc in products_ref.stream():
                data = doc.to_dict()
                
                # جلب اسم المشتري
                buyer_name = data.get('buyer_name', '')
                buyer_id = data.get('buyer_id', '')
                
                # إذا كان المنتج مباعاً ولا يوجد اسم للمشتري، نجلبه من مجموعة users
                if data.get('sold') and buyer_id:
                    if not buyer_name or buyer_name == '':
                        try:
                            buyer_doc = db.collection('users').document(str(buyer_id)).get()
                            if buyer_doc.exists:
                                buyer_data = buyer_doc.to_dict()
                                # محاولة جلب الاسم من عدة حقول
                                buyer_name = buyer_data.get('name') or buyer_data.get('username') or buyer_data.get('telegram_name') or ''
                                print(f"📦 المشتري {buyer_id}: بيانات = {buyer_data}")
                            else:
                                print(f"⚠️ المستخدم {buyer_id} غير موجود في users")
                        except Exception as e:
                            print(f"⚠️ خطأ في جلب بيانات المشتري {buyer_id}: {e}")
                    
                    # إذا لا يزال فارغاً، نضع نص افتراضي
                    if not buyer_name:
                        buyer_name = f'مستخدم {buyer_id}'
                
                product_info = {
                    'id': doc.id,
                    'item_name': data.get('item_name', 'منتج'),
                    'price': data.get('price', 0),
                    'category': data.get('category', ''),
                    'seller_name': data.get('seller_name', 'المتجر'),
                    'delivery_type': data.get('delivery_type', 'instant'),
                    'sold': data.get('sold', False),
                    'buyer_id': buyer_id,
                    'buyer_name': buyer_name,
                    'sold_at': str(data.get('sold_at', '')),
                    'created_at': str(data.get('created_at', ''))
                }
                if data.get('sold'):
                    sold_products_list.append(product_info)
                else:
                    available_products_list.append(product_info)
        except Exception as e:
            print(f"⚠️ خطأ في جلب products: {e}")
        
        # 6️⃣ إحصائيات
        stats = {
            'total_payments': len(pending_payments_list),
            'completed_payments': len([p for p in pending_payments_list if p['status'] == 'completed']),
            'pending_payments': len([p for p in pending_payments_list if p['status'] == 'pending']),
            'total_merchant_invoices': len(merchant_invoices_list),
            'total_charges': len(charge_history_list),
            'total_orders': len(orders_list),
            'sold_products': len(sold_products_list),
            'available_products': len(available_products_list),
            'total_revenue': sum([o['price'] for o in orders_list]),
            'total_charged': sum([c['amount'] for c in charge_history_list])
        }
        
        return jsonify({
            'status': 'success',
            'pending_payments': pending_payments_list,
            'merchant_invoices': merchant_invoices_list,
            'charge_history': charge_history_list,
            'orders': orders_list,
            'sold_products': sold_products_list,
            'available_products': available_products_list,
            'stats': stats
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب الفواتير: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})

# API لجلب جميع المنتجات (للمالك)
@app.route('/api/admin/get_products')
def api_get_products():
    # التحقق من الصلاحية
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        available = []
        sold = []
        
        if db:
            # جلب جميع المنتجات من Firebase
            products_ref = db.collection('products')
            
            # المنتجات المتاحة
            available_query = query_where(products_ref, 'sold', '==', False)
            for doc in available_query.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                available.append(data)
            
            # المنتجات المباعة
            sold_query = query_where(products_ref, 'sold', '==', True)
            for doc in sold_query.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                sold.append(data)
        
        return jsonify({
            'status': 'success',
            'available': available,
            'sold': sold
        })
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لإضافة منتج جديد (للمالك)
@app.route('/api/admin/add_product_new', methods=['POST'])
def api_add_product_new():
    # التحقق من الصلاحية
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        name = data.get('name', '').strip()
        price = float(data.get('price', 0))
        category = data.get('category', '').strip()
        details = data.get('details', '').strip()
        hidden_data = data.get('hidden_data', '').strip()
        buyer_instructions = data.get('buyer_instructions', '').strip()
        image = data.get('image', '').strip()
        delivery_type = data.get('delivery_type', 'instant').strip()
        
        # التحقق من نوع التسليم
        if delivery_type not in ['instant', 'manual']:
            delivery_type = 'instant'
        
        # التحقق من البيانات الأساسية
        if not name or price <= 0 or not category:
            return jsonify({'status': 'error', 'message': 'بيانات ناقصة (الاسم، السعر، الفئة)'})
        
        # التحقق حسب نوع التسليم
        if delivery_type == 'instant' and not hidden_data:
            return jsonify({'status': 'error', 'message': 'البيانات السرية مطلوبة للتسليم الفوري'})
        
        if delivery_type == 'manual' and not buyer_instructions:
            return jsonify({'status': 'error', 'message': 'يجب تحديد ما تحتاجه من المشتري'})
        
        # إنشاء المنتج
        product_id = str(uuid.uuid4())
        
        # تشفير البيانات السرية قبل الحفظ
        encrypted_hidden_data = encrypt_data(hidden_data) if hidden_data else ''
        
        product_data = {
            'id': product_id,
            'item_name': name,
            'price': price,
            'category': category,
            'details': details,
            'hidden_data': encrypted_hidden_data,
            'buyer_instructions': buyer_instructions,
            'image_url': image,
            'seller_id': ADMIN_ID,
            'seller_name': 'المتجر الرسمي',
            'delivery_type': delivery_type,
            'sold': False,
            'created_at': time.time()
        }
        
        # حفظ في Firebase
        if db:
            db.collection('products').document(product_id).set(product_data)
            print(f"✅ تم حفظ المنتج في Firebase: {name} (التسليم: {delivery_type})")
        
        return jsonify({'status': 'success', 'product_id': product_id})
        
    except Exception as e:
        logger.error(f"Error adding product: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لحذف منتج (للمالك)
@app.route('/api/admin/delete_product', methods=['POST'])
def api_delete_product():
    # التحقق من الصلاحية
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        product_id = data.get('product_id')
        
        if not product_id:
            return jsonify({'status': 'error', 'message': 'معرف المنتج مطلوب'})
        
        # حذف من Firebase
        delete_product(product_id)
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# ============ إدارة الأقسام ============

# API لجلب الأقسام
@app.route('/api/admin/get_categories', methods=['GET'])
def api_get_categories():
    """جلب قائمة الأقسام"""
    # ✅ التحقق من صلاحية الأدمن
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        # جلب المنتجات من Firebase لحساب العدد
        all_products = get_all_products_for_store()
        category_counts = {}
        for item in all_products:
            cat = item.get('category', '')
            if cat:
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        # جلب الأقسام من Firebase
        categories = get_categories_list()
        
        # إضافة عدد المنتجات لكل قسم
        result = []
        for cat in categories:
            cat_data = cat.copy()
            cat_data['product_count'] = category_counts.get(cat['name'], 0)
            result.append(cat_data)
        
        return jsonify({'status': 'success', 'categories': result})
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لإضافة قسم جديد
@app.route('/api/admin/add_category', methods=['POST'])
def api_add_category():
    """إضافة قسم جديد"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        name = data.get('name', '').strip()
        image_url = data.get('image_url', '').strip()
        delivery_type = data.get('delivery_type', 'instant').strip()
        
        if delivery_type not in ['instant', 'manual']:
            delivery_type = 'instant'
        
        if not name:
            return jsonify({'status': 'error', 'message': 'اسم القسم مطلوب'})
        
        # جلب الأقسام الحالية من Firebase
        current_categories = get_categories()
        
        # التحقق من عدم تكرار الاسم
        for cat in current_categories:
            if cat['name'] == name:
                return jsonify({'status': 'error', 'message': 'هذا القسم موجود مسبقاً'})
        
        # إنشاء القسم الجديد
        import uuid
        cat_id = str(uuid.uuid4())[:8]
        new_order = len(current_categories) + 1
        
        new_category = {
            'id': cat_id,
            'name': name,
            'image_url': image_url or 'https://placehold.co/100x100/6c5ce7/ffffff?text=' + name,
            'order': new_order,
            'delivery_type': delivery_type,
            'created_at': time.time()
        }
        
        # حفظ في Firebase
        if db:
            db.collection('categories').document(cat_id).set(new_category)
            print(f"✅ تم حفظ القسم في Firebase: {name} ({delivery_type})")
        
        return jsonify({'status': 'success', 'category': new_category})
        
    except Exception as e:
        logger.error(f"Error adding category: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لتعديل قسم
@app.route('/api/admin/update_category', methods=['POST'])
def api_update_category():
    """تعديل قسم موجود"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        cat_id = data.get('id')
        new_name = data.get('name', '').strip()
        new_image = data.get('image_url', '').strip()
        new_delivery_type = data.get('delivery_type', '').strip()
        
        if not cat_id:
            return jsonify({'status': 'error', 'message': 'معرف القسم مطلوب'})
        
        # جلب القسم من Firebase
        cat_found = get_category_by_id(cat_id)
        
        if not cat_found:
            return jsonify({'status': 'error', 'message': 'القسم غير موجود'})
        
        old_name = cat_found.get('name', '')
        
        # بناء بيانات التحديث
        update_data = {}
        if new_name:
            update_data['name'] = new_name
        if new_image:
            update_data['image_url'] = new_image
        if new_delivery_type in ['instant', 'manual']:
            update_data['delivery_type'] = new_delivery_type
        
        # تحديث في Firebase
        update_category(cat_id, update_data)
        
        # تحديث اسم القسم في المنتجات إذا تغير
        if old_name and new_name and old_name != new_name:
            all_products = get_all_products_for_store()
            for item in all_products:
                if item.get('category') == old_name:
                    # تحديث في Firebase
                    if item.get('id'):
                        try:
                            db.collection('products').document(item['id']).update({'category': new_name})
                        except:
                            pass
        
        cat_found.update(update_data)
        return jsonify({'status': 'success', 'category': cat_found})
        
    except Exception as e:
        logger.error(f"Error updating category: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لحذف قسم
@app.route('/api/admin/delete_category', methods=['POST'])
def api_delete_category():
    """حذف قسم"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        cat_id = data.get('id')
        
        if not cat_id:
            return jsonify({'status': 'error', 'message': 'معرف القسم مطلوب'})
        
        # جلب القسم من Firebase
        cat_found = get_category_by_id(cat_id)
        
        if not cat_found:
            return jsonify({'status': 'error', 'message': 'القسم غير موجود'})
        
        # التحقق من عدد المنتجات في القسم
        product_count = count_products_in_category(cat_found.get('name', ''))
        
        if product_count > 0:
            return jsonify({
                'status': 'error', 
                'message': f'لا يمكن حذف القسم - يوجد {product_count} منتج فيه'
            })
        
        # حذف من Firebase
        delete_category(cat_id)
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لإعادة ترتيب الأقسام
@app.route('/api/admin/reorder_categories', methods=['POST'])
def api_reorder_categories():
    """إعادة ترتيب الأقسام"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        new_order = data.get('order', [])  # قائمة بمعرفات الأقسام بالترتيب الجديد
        
        if not new_order:
            return jsonify({'status': 'error', 'message': 'الترتيب مطلوب'})
        
        # تحديث الترتيب في Firebase
        for idx, cat_id in enumerate(new_order):
            if db:
                try:
                    db.collection('categories').document(cat_id).update({'order': idx + 1})
                except:
                    pass
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error reordering categories: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لجلب الأقسام للعرض العام (بدون تسجيل دخول)
@app.route('/api/categories', methods=['GET'])
def api_public_categories():
    """جلب الأقسام للعرض في الموقع"""
    try:
        categories = get_categories_list()
        result = []
        for cat in categories:
            result.append({
                'name': cat['name'],
                'image_url': cat.get('image_url', ''),
                'delivery_type': cat.get('delivery_type', 'instant')
            })
        return jsonify({
            'status': 'success', 
            'categories': result,
            'columns': display_settings.get('categories_columns', 3)
        })
    except Exception as e:
        logger.error(f"Error in public categories: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# API لجلب إعدادات العرض
@app.route('/api/admin/get_display_settings', methods=['GET'])
def api_get_display_settings():
    """جلب إعدادات العرض"""
    # ✅ التحقق من صلاحية الأدمن
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    return jsonify({
        'status': 'success',
        'categories_columns': display_settings.get('categories_columns', 3)
    })

# API لتعديل إعدادات العرض
@app.route('/api/admin/set_display_settings', methods=['POST'])
def api_set_display_settings():
    """تعديل إعدادات العرض"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        cols = data.get('categories_columns')
        
        if cols and cols in [2, 3, 4]:
            display_settings['categories_columns'] = cols
            
            # حفظ في Firebase
            if db:
                db.collection('settings').document('display').set({
                    'categories_columns': cols
                }, merge=True)
            
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'message': 'قيمة غير صالحة'})
            
    except Exception as e:
        logger.error(f"Error setting display settings: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

# تحميل البيانات من Firebase عند بدء التشغيل (يعمل مع Gunicorn وlocal)
print("🚀 بدء تشغيل التطبيق...")
load_all_data_from_firebase()

if __name__ == "__main__":
    # هذا السطر يجعل البوت يعمل على المنفذ الصحيح في ريندر أو 10000 في جهازك
    port = int(os.environ.get("PORT", 10000))
    print(f"✅ التطبيق يعمل على المنفذ {port}")
    app.run(host="0.0.0.0", port=port)
