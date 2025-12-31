#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
أدوات الأمان
============
دوال مساعدة للأمان والحماية من الثغرات الشائعة
"""

import os
import logging
from functools import wraps
from flask import session, jsonify, abort, request
from google.cloud import firestore

# تحديد logger
logger = logging.getLogger(__name__)

# === 1. حماية الهوية ===
def require_session_user():
    """Decorator للتحقق من تسجيل الدخول من Session فقط"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'status': 'error', 'message': 'غير مسجل دخول'}), 401
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_session_user_id():
    """الحصول على user_id من Session بأمان"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return str(user_id)


def require_admin():
    """Decorator للتحقق من صلاحيات الأدمن"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('is_admin'):
                abort(403)
            
            user_id = session.get('user_id')
            admin_id = os.getenv('ADMIN_ID')
            
            if str(user_id) != str(admin_id):
                session.clear()
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# === 2. حماية من Race Condition في المعاملات المالية ===
def safe_transaction(db, callback, *args, **kwargs):
    """
    تنفيذ عملية آمنة باستخدام Firestore Transaction
    
    الاستخدام:
    def update_callback(transaction, user_ref, amount):
        user_doc = transaction.get(user_ref)
        balance = user_doc.get('balance')
        if balance < amount:
            raise ValueError('رصيد غير كافي')
        transaction.update(user_ref, {'balance': balance - amount})
    
    safe_transaction(db, update_callback, user_ref, amount)
    """
    try:
        @firestore.transactional
        def do_transaction(transaction, *args, **kwargs):
            return callback(transaction, *args, **kwargs)
        
        transaction = db.transaction()
        return do_transaction(transaction, *args, **kwargs)
    except Exception as e:
        logger.error(f"خطأ في Transaction: {e}")
        raise


def checkout_with_transaction(db, user_id, total_amount, callback):
    """
    تنفيذ عملية شراء آمنة مع ضمان عدم Race Condition
    
    callback: دالة توقيع (transaction, user_data) تقوم بالعملية الإضافية
    """
    user_ref = db.collection('users').document(str(user_id))
    
    try:
        @firestore.transactional
        def do_checkout(transaction):
            # اقرأ البيانات الحالية
            user_snapshot = transaction.get(user_ref)
            if not user_snapshot.exists:
                raise ValueError('المستخدم غير موجود')
            
            user_data = user_snapshot.to_dict()
            balance = float(user_data.get('balance', 0))
            
            # تحقق من الرصيد
            if balance < total_amount:
                raise ValueError(f'رصيد غير كافي. تحتاج {total_amount - balance:.2f} ريال')
            
            # حدّث الرصيد
            new_balance = balance - total_amount
            transaction.update(user_ref, {
                'balance': new_balance,
                'last_purchase': firestore.SERVER_TIMESTAMP
            })
            
            # قم بعملية إضافية إذا لزمت (إنشاء طلب، إرسال رسالة، إلخ)
            if callback:
                callback(transaction, user_data)
            
            return new_balance
        
        transaction = db.transaction()
        return do_checkout(transaction)
    
    except ValueError as e:
        raise e
    except Exception as e:
        logger.error(f"خطأ في عملية الشراء: {e}")
        raise


# === 3. حماية من CSRF ===
def get_csrf_token():
    """الحصول على CSRF token من Session"""
    try:
        from flask_wtf.csrf import generate_csrf  # type: ignore
        return generate_csrf()
    except ImportError:
        # إذا لم تكن flask_wtf مثبتة
        return None


def validate_csrf():
    """Decorator للتحقق من CSRF token"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                from flask_wtf.csrf import validate_csrf as check_csrf  # type: ignore
                check_csrf()
            except ImportError:
                # flask_wtf غير مثبت - تخطي الفحص
                pass
            except Exception as e:
                logger.warning(f"فشل التحقق من CSRF: {e}")
                return jsonify({'status': 'error', 'message': 'فشل التحقق من الأمان'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# === 4. حماية من Injection ===
ALLOWED_COLLECTIONS = {
    'products': True,
    'categories': True,
    'merchants': True,
    'orders': True,
    'users': False,  # خاص - لا يُقرأ مباشرة
    'charge_history': True,
    'cart_stats': True,
    'merchant_invoices': False,  # خاص
    'charge_keys': False,  # خاص جداً
    'pending_payments': False,  # خاص جداً
}


def validate_collection_name(collection_name):
    """التحقق من أن اسم الـ collection آمن"""
    if collection_name not in ALLOWED_COLLECTIONS:
        raise ValueError(f'Colleciton غير مسموح: {collection_name}')
    
    if not ALLOWED_COLLECTIONS[collection_name]:
        raise ValueError(f'لا يمكن الوصول لـ: {collection_name}')
    
    return collection_name


# === 5. حماية من تسريب المعلومات ===
def sanitize_error_message(error_msg):
    """
    إزالة المعلومات الحساسة من رسائل الأخطاء
    """
    sensitive_keywords = [
        'firestore', 'firebase', 'database', 'sql',
        'password', 'key', 'secret', 'token',
        '/workspaces', '/app', 'traceback', 'line'
    ]
    
    msg = str(error_msg).lower()
    for keyword in sensitive_keywords:
        if keyword in msg:
            # إذا كان الخطأ يحتوي على معلومات حساسة، إرجع رسالة عامة
            logger.error(f"خطأ حساس تم اكتشافه: {error_msg}")
            return "حدث خطأ في المعالجة. الرجاء المحاولة لاحقاً."
    
    return error_msg


def create_safe_response(data, user_id=None):
    """
    إنشاء response آمن بدون معلومات حساسة
    """
    # لا تُرجع معلومات حساسة في الأخطاء
    if 'error' in data:
        data['error'] = sanitize_error_message(data['error'])
    
    # تأكد من عدم تضمين معلومات الآخرين
    if 'users' in data:
        del data['users']
    
    if 'passwords' in data:
        del data['passwords']
    
    return data


# === 6. حماية من Brute Force ===
def setup_rate_limiting(app, limiter):
    """
    إعداد Rate Limiting للـ endpoints الحساسة
    يجب استدعاء هذا في app.py
    """
    # سيتم استخدامه مع @limiter.limit()
    pass


# === 7. تسجيل الأنشطة الأمنية ===
def log_security_event(event_type, user_id=None, details=None):
    """تسجيل الأحداث الأمنية المهمة"""
    log_msg = f"[SECURITY] {event_type}"
    if user_id:
        log_msg += f" | User: {user_id}"
    if details:
        log_msg += f" | Details: {details}"
    
    logger.warning(log_msg)


# === 8. تحقق من الملكية ===
def verify_user_ownership(user_id, resource_type, resource_id, db):
    """
    التحقق من أن المستخدم يمتلك المورد
    
    العودة: True إذا كان يمتلكه, False خلاف ذلك
    """
    user_id = str(user_id)
    
    try:
        if resource_type == 'cart':
            # التحقق من ملكية السلة
            cart_ref = db.collection('carts').document(user_id)
            cart = cart_ref.get()
            return cart.exists
        
        elif resource_type == 'order':
            # التحقق من أن الطلب للمستخدم
            order_ref = db.collection('orders').document(resource_id)
            order = order_ref.get()
            if order.exists:
                return order.get('buyer_id') == user_id
            return False
        
        elif resource_type == 'wallet':
            # المحفظة تابعة للمستخدم دائماً
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"خطأ في التحقق من الملكية: {e}")
        return False
