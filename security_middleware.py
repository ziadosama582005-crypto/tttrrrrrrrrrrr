#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Security Middleware - طبقة الحماية المتقدمة
============================================
يحتوي على:
1. CSRF Protection - حماية النماذج
2. OTP للسحب - رمز تحقق عبر Telegram
3. تنبيهات تسجيل الدخول الجديد
4. كشف تغير الجهاز/IP
"""

import os
import time
import random
import string
import hashlib
import logging
from functools import wraps
from flask import session, request, jsonify, abort
from datetime import datetime
import json

logger = logging.getLogger(__name__)

# ==================== 1. CSRF Protection ====================

# تخزين مؤقت لـ CSRF tokens
_csrf_tokens = {}  # {session_id: {'token': 'xxx', 'created_at': timestamp}}
CSRF_TOKEN_EXPIRY = 3600  # ساعة واحدة

def generate_csrf_token():
    """توليد CSRF token آمن"""
    try:
        # إنشاء token عشوائي
        token = hashlib.sha256(os.urandom(32)).hexdigest()
        
        # تخزينه في Session
        session['csrf_token'] = token
        session['csrf_created_at'] = time.time()
        
        return token
    except Exception as e:
        logger.error(f"خطأ في توليد CSRF token: {e}")
        return None


def get_csrf_token():
    """الحصول على CSRF token الحالي أو إنشاء جديد"""
    token = session.get('csrf_token')
    created_at = session.get('csrf_created_at', 0)
    
    # التحقق من صلاحية الـ token
    if token and (time.time() - created_at) < CSRF_TOKEN_EXPIRY:
        return token
    
    # إنشاء token جديد
    return generate_csrf_token()


def validate_csrf_token(token):
    """التحقق من صحة CSRF token"""
    stored_token = session.get('csrf_token')
    created_at = session.get('csrf_created_at', 0)
    
    # التحقق من وجود الـ token
    if not stored_token or not token:
        return False
    
    # التحقق من الصلاحية
    if (time.time() - created_at) > CSRF_TOKEN_EXPIRY:
        return False
    
    # مقارنة آمنة
    return hashlib.sha256(token.encode()).digest() == hashlib.sha256(stored_token.encode()).digest()


def csrf_protect(f):
    """Decorator لحماية الـ routes من CSRF"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            # الحصول على الـ token من الـ request
            token = (
                request.form.get('csrf_token') or
                request.headers.get('X-CSRF-Token') or
                (request.get_json(silent=True) or {}).get('csrf_token')
            )
            
            if not validate_csrf_token(token):
                logger.warning(f"🚫 CSRF فاشل من {request.remote_addr}")
                return jsonify({'success': False, 'message': 'فشل التحقق من الأمان. يرجى إعادة تحميل الصفحة'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ==================== 2. OTP للسحب عبر Telegram ====================

# تخزين أكواد OTP
_withdrawal_otp = {}  # {user_id: {'code': '123456', 'amount': 100, 'created_at': timestamp, 'attempts': 0}}
OTP_EXPIRY = 300  # 5 دقائق
MAX_OTP_ATTEMPTS = 3


def generate_withdrawal_otp(user_id, amount, withdraw_type):
    """
    توليد OTP لعملية السحب
    
    Returns:
        str: كود OTP أو None في حالة الخطأ
    """
    try:
        # توليد كود 6 أرقام
        code = ''.join(random.choices(string.digits, k=6))
        
        # تخزين الكود
        _withdrawal_otp[str(user_id)] = {
            'code': code,
            'amount': amount,
            'withdraw_type': withdraw_type,
            'created_at': time.time(),
            'attempts': 0
        }
        
        return code
    except Exception as e:
        logger.error(f"خطأ في توليد OTP: {e}")
        return None


def verify_withdrawal_otp(user_id, code, amount=None):
    """
    التحقق من OTP السحب
    
    Returns:
        tuple: (success: bool, message: str)
    """
    user_id = str(user_id)
    
    # التحقق من وجود OTP
    if user_id not in _withdrawal_otp:
        return False, 'لم يتم إرسال رمز التحقق. اطلب رمزاً جديداً'
    
    otp_data = _withdrawal_otp[user_id]
    
    # التحقق من انتهاء الصلاحية
    if (time.time() - otp_data['created_at']) > OTP_EXPIRY:
        del _withdrawal_otp[user_id]
        return False, 'انتهت صلاحية رمز التحقق. اطلب رمزاً جديداً'
    
    # التحقق من عدد المحاولات
    if otp_data['attempts'] >= MAX_OTP_ATTEMPTS:
        del _withdrawal_otp[user_id]
        return False, 'تم تجاوز الحد الأقصى للمحاولات. اطلب رمزاً جديداً'
    
    # زيادة عداد المحاولات
    _withdrawal_otp[user_id]['attempts'] += 1
    
    # التحقق من الكود
    if otp_data['code'] != code:
        remaining = MAX_OTP_ATTEMPTS - otp_data['attempts']
        return False, f'رمز التحقق غير صحيح. {remaining} محاولات متبقية'
    
    # التحقق من المبلغ (إذا تم تمريره)
    if amount is not None and float(otp_data['amount']) != float(amount):
        return False, 'المبلغ لا يتطابق مع طلب الرمز الأصلي'
    
    # حذف OTP بعد الاستخدام الناجح
    del _withdrawal_otp[user_id]
    
    return True, 'تم التحقق بنجاح'


def get_otp_data(user_id):
    """الحصول على بيانات OTP للمستخدم"""
    return _withdrawal_otp.get(str(user_id))


def send_withdrawal_otp(bot, user_id, amount, withdraw_type, net_amount):
    """
    إرسال OTP للمستخدم عبر Telegram
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # توليد الكود
        code = generate_withdrawal_otp(user_id, amount, withdraw_type)
        
        if not code:
            return False, 'فشل في توليد رمز التحقق'
        
        # تحديد نوع السحب
        type_text = "عادي (6%)" if withdraw_type == 'normal' else "⚡ فوري (8.5%)"
        
        # إرسال الرسالة
        message = f"""
🔐 <b>رمز تأكيد السحب</b>

📌 نوع السحب: {type_text}
💰 المبلغ: {amount:.2f} ريال
✅ الصافي: {net_amount:.2f} ريال

🔢 <b>رمز التحقق:</b>
<code>{code}</code>

⏰ صالح لمدة 5 دقائق فقط
⚠️ لا تشارك هذا الرمز مع أي شخص!
"""
        bot.send_message(int(user_id), message, parse_mode='HTML')
        
        return True, 'تم إرسال رمز التحقق إلى حسابك في تيليجرام'
    
    except Exception as e:
        logger.error(f"خطأ في إرسال OTP: {e}")
        return False, 'فشل في إرسال رمز التحقق'


# ==================== 3. تنبيهات تسجيل الدخول الجديد ====================

def get_device_fingerprint():
    """الحصول على بصمة الجهاز من الـ request"""
    user_agent = request.headers.get('User-Agent', '')
    accept_lang = request.headers.get('Accept-Language', '')
    
    # إنشاء hash للبصمة
    fingerprint = hashlib.md5(f"{user_agent}|{accept_lang}".encode()).hexdigest()[:16]
    
    return {
        'fingerprint': fingerprint,
        'user_agent': user_agent[:200],  # تقليص الحجم
        'ip': get_real_ip(),
        'timestamp': time.time()
    }


def get_real_ip():
    """الحصول على IP الحقيقي (مع مراعاة الـ proxy)"""
    # Cloudflare
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')
    
    # X-Forwarded-For
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    
    # X-Real-IP
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    
    # الـ IP المباشر
    return request.remote_addr


def detect_new_login(db, user_id, bot=None):
    """
    كشف تسجيل دخول من جهاز جديد
    
    Returns:
        dict: {'is_new': bool, 'device_info': dict}
    """
    try:
        current_device = get_device_fingerprint()
        user_id = str(user_id)
        
        # جلب الأجهزة المسجلة للمستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return {'is_new': False, 'device_info': current_device}
        
        user_data = user_doc.to_dict()
        known_devices = user_data.get('known_devices', [])
        
        # البحث عن الجهاز الحالي
        is_new_device = True
        for device in known_devices:
            if device.get('fingerprint') == current_device['fingerprint']:
                is_new_device = False
                break
        
        # إذا كان جهاز جديد
        if is_new_device:
            # إضافة الجهاز للقائمة
            known_devices.append(current_device)
            
            # الاحتفاظ بآخر 10 أجهزة فقط
            if len(known_devices) > 10:
                known_devices = known_devices[-10:]
            
            # تحديث قاعدة البيانات
            user_ref.update({
                'known_devices': known_devices,
                'last_login': datetime.now(),
                'last_login_ip': current_device['ip']
            })
            
            # إرسال تنبيه للمستخدم
            if bot:
                try:
                    send_new_login_alert(bot, user_id, current_device, user_data.get('name', 'المستخدم'))
                except Exception as e:
                    logger.error(f"خطأ في إرسال تنبيه الدخول: {e}")
        
        return {'is_new': is_new_device, 'device_info': current_device}
    
    except Exception as e:
        logger.error(f"خطأ في كشف الجهاز الجديد: {e}")
        return {'is_new': False, 'device_info': {}}


def send_new_login_alert(bot, user_id, device_info, user_name):
    """إرسال تنبيه بتسجيل دخول من جهاز جديد"""
    try:
        # تحليل User-Agent
        user_agent = device_info.get('user_agent', '')
        
        # تحديد نوع الجهاز
        if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
            device_type = '📱 هاتف'
        elif 'Tablet' in user_agent or 'iPad' in user_agent:
            device_type = '📟 تابلت'
        else:
            device_type = '💻 كمبيوتر'
        
        # تحديد المتصفح
        if 'Chrome' in user_agent:
            browser = 'Chrome'
        elif 'Firefox' in user_agent:
            browser = 'Firefox'
        elif 'Safari' in user_agent:
            browser = 'Safari'
        elif 'Edge' in user_agent:
            browser = 'Edge'
        else:
            browser = 'متصفح آخر'
        
        # الوقت
        login_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        message = f"""
🔔 <b>تنبيه أمني - تسجيل دخول جديد</b>

مرحباً {user_name}،

تم تسجيل الدخول لحسابك من جهاز جديد:

{device_type} • {browser}
🌐 IP: {device_info.get('ip', 'غير معروف')}
🕐 الوقت: {login_time}

✅ إذا كان هذا أنت، تجاهل هذه الرسالة.

⚠️ إذا لم تكن أنت:
1. قم بتغيير كود الدخول فوراً
2. فعّل التحقق بخطوتين (2FA)
3. تواصل معنا للمساعدة
"""
        bot.send_message(int(user_id), message, parse_mode='HTML')
        logger.info(f"✅ تم إرسال تنبيه دخول جديد للمستخدم {user_id}")
        
    except Exception as e:
        logger.error(f"خطأ في إرسال تنبيه الدخول: {e}")


# ==================== 4. Session Security ====================

def bind_session_to_ip():
    """ربط الجلسة بالـ IP (اختياري - يمكن تعطيله)"""
    if 'session_ip' not in session:
        session['session_ip'] = get_real_ip()
        return True
    
    if session['session_ip'] != get_real_ip():
        # IP تغير - قد يكون اختراق
        logger.warning(f"⚠️ تغير IP للجلسة: {session['session_ip']} -> {get_real_ip()}")
        return False
    
    return True


def refresh_session():
    """تحديث بيانات الجلسة بشكل دوري"""
    session['last_activity'] = time.time()
    
    # تجديد CSRF token كل 30 دقيقة
    csrf_created = session.get('csrf_created_at', 0)
    if (time.time() - csrf_created) > 1800:  # 30 دقيقة
        generate_csrf_token()


# ==================== Context Processor ====================

def inject_security_context():
    """
    دالة لحقن متغيرات الأمان في جميع القوالب
    
    الاستخدام في app.py:
    from security_middleware import inject_security_context
    
    @app.context_processor
    def security_context():
        return inject_security_context()
    """
    return {
        'csrf_token': get_csrf_token
    }


# ==================== Cleanup ====================

def cleanup_expired_otps():
    """تنظيف OTPs منتهية الصلاحية"""
    current_time = time.time()
    expired = []
    
    for user_id, data in _withdrawal_otp.items():
        if (current_time - data['created_at']) > OTP_EXPIRY:
            expired.append(user_id)
    
    for user_id in expired:
        del _withdrawal_otp[user_id]
    
    if expired:
        logger.info(f"🧹 تم حذف {len(expired)} OTPs منتهية")
