#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
أدوات Firebase
===============
جميع دوال التعامل مع قاعدة بيانات Firebase
"""

import os
import json
import time
import uuid

# استيراد firestore للـ SERVER_TIMESTAMP
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

# استيراد من extensions لتجنب circular imports
from extensions import db, FIREBASE_AVAILABLE

# محاولة استيراد FieldFilter للنسخ الجديدة
USE_FIELD_FILTER = False
try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    USE_FIELD_FILTER = True
except ImportError:
    USE_FIELD_FILTER = False

# === دالة Query متوافقة ===
def query_where(collection_ref, field, op, value):
    """استخدام where بطريقة متوافقة مع جميع النسخ"""
    if USE_FIELD_FILTER:
        return collection_ref.where(filter=FieldFilter(field, op, value))
    else:
        return collection_ref.where(field, op, value)

# === دوال الرصيد ===
def get_balance(user_id):
    """جلب رصيد المستخدم من Firebase"""
    try:
        if not db:
            return 0.0
        uid = str(user_id)
        doc = db.collection('users').document(uid).get()
        if doc.exists:
            return doc.to_dict().get('balance', 0.0)
        return 0.0
    except Exception as e:
        print(f"⚠️ خطأ في جلب الرصيد: {e}")
        return 0.0

def add_balance(user_id, amount, users_wallets=None, description='شحن رصيد', order_id=''):
    """إضافة رصيد للمستخدم في Firebase والذاكرة"""
    uid = str(user_id)
    
    # تحديث الذاكرة إذا تم تمريرها
    if users_wallets is not None:
        if uid not in users_wallets:
            users_wallets[uid] = 0.0
        users_wallets[uid] += float(amount)
    
    # جلب الرصيد الحالي من Firebase
    current_balance = get_balance(uid)
    new_balance = current_balance + float(amount)
    
    # حفظ في Firebase
    try:
        if db:
            db.collection('users').document(uid).set({
                'balance': new_balance,
                'telegram_id': uid,
                'updated_at': firestore.SERVER_TIMESTAMP,
                'last_charge_at': firestore.SERVER_TIMESTAMP  # تحديث وقت آخر شحن للسحب
            }, merge=True)
            print(f"✅ تم حفظ رصيد المستخدم {uid}: {new_balance} ريال في Firestore")
            
            # تسجيل العملية في balance_logs
            add_balance_log(
                user_id=uid,
                amount=amount,
                operation_type='credit',
                description=description,
                order_id=order_id,
                old_balance=current_balance,
                new_balance=new_balance
            )
            
            return new_balance
    except Exception as e:
        print(f"❌ خطأ في حفظ الرصيد إلى Firebase: {e}")
    
    return new_balance

def deduct_balance(user_id, amount, users_wallets=None, description='خصم رصيد', order_id=''):
    """خصم رصيد من المستخدم"""
    uid = str(user_id)
    
    # تحديث الذاكرة إذا تم تمريرها
    if users_wallets is not None:
        if uid in users_wallets:
            users_wallets[uid] -= float(amount)
    
    # جلب الرصيد الحالي من Firebase
    current_balance = get_balance(uid)
    new_balance = current_balance - float(amount)
    
    # حفظ في Firebase
    try:
        if db:
            db.collection('users').document(uid).set({
                'balance': new_balance,
                'telegram_id': uid,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)
            print(f"✅ تم خصم {amount} ريال من المستخدم {uid}. الرصيد الجديد: {new_balance}")
            
            # تسجيل العملية في balance_logs
            add_balance_log(
                user_id=uid,
                amount=amount,
                operation_type='debit',
                description=description,
                order_id=order_id,
                old_balance=current_balance,
                new_balance=new_balance
            )
            
            return new_balance
    except Exception as e:
        print(f"❌ خطأ في خصم الرصيد: {e}")
    
    return new_balance

# === دوال المنتجات ===
def get_products(sold=False):
    """جلب المنتجات من Firebase"""
    try:
        if not db:
            return []
        products_ref = query_where(db.collection('products'), 'sold', '==', sold)
        products = []
        for doc in products_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            products.append(data)
        return products
    except Exception as e:
        print(f"⚠️ خطأ في جلب المنتجات: {e}")
        return []

def get_product_by_id(product_id):
    """جلب منتج بالـ ID"""
    try:
        if not db:
            return None
        doc = db.collection('products').document(product_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    except Exception as e:
        print(f"⚠️ خطأ في جلب المنتج: {e}")
        return None

def add_product(product_data):
    """إضافة منتج جديد"""
    try:
        if not db:
            return None
        product_id = str(uuid.uuid4())
        product_data['created_at'] = firestore.SERVER_TIMESTAMP
        product_data['sold'] = False
        db.collection('products').document(product_id).set(product_data)
        return product_id
    except Exception as e:
        print(f"❌ خطأ في إضافة المنتج: {e}")
        return None

def update_product(product_id, data):
    """تحديث منتج"""
    try:
        if not db:
            return False
        db.collection('products').document(product_id).update(data)
        return True
    except Exception as e:
        print(f"❌ خطأ في تحديث المنتج: {e}")
        return False

def mark_product_sold(product_id, buyer_id, buyer_name):
    """تعليم المنتج كمباع"""
    try:
        if not db:
            return False
        db.collection('products').document(product_id).update({
            'sold': True,
            'buyer_id': str(buyer_id),
            'buyer_name': buyer_name,
            'sold_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"❌ خطأ في تعليم المنتج كمباع: {e}")
        return False

# === دوال الأقسام ===
def get_categories():
    """جلب الأقسام من Firebase"""
    try:
        if not db:
            return []
        categories = []
        for doc in db.collection('categories').order_by('order').stream():
            data = doc.to_dict()
            data['id'] = doc.id
            categories.append(data)
        return categories
    except Exception as e:
        print(f"⚠️ خطأ في جلب الأقسام: {e}")
        return []

# === إعدادات واجهة المستخدم (settings) ===
def get_header_settings():
    """جلب إعدادات الشريط أعلى الهيدر"""
    defaults = {
        'enabled': False,
        'text': '',
        'link_url': ''
    }

    try:
        if not db:
            return defaults

        doc = db.collection('settings').document('header').get()
        if not doc.exists:
            return defaults

        data = doc.to_dict() or {}
        # دمج القيم الافتراضية لحماية القوالب من مفاتيح ناقصة
        return {**defaults, **data}
    except Exception as e:
        print(f"⚠️ خطأ في جلب إعدادات الهيدر: {e}")
        return defaults


def set_header_settings(enabled=False, text='', link_url=''):
    """تحديث إعدادات الشريط أعلى الهيدر"""
    try:
        if not db:
            return False

        db.collection('settings').document('header').set({
            'enabled': bool(enabled),
            'text': str(text or '').strip(),
            'link_url': str(link_url or '').strip(),
            'updated_at': firestore.SERVER_TIMESTAMP if firestore else None
        }, merge=True)
        return True
    except Exception as e:
        print(f"❌ خطأ في تحديث إعدادات الهيدر: {e}")
        return False

def add_category(name, image_url='', delivery_type='instant', order=999):
    """إضافة قسم جديد"""
    try:
        if not db:
            return None
        cat_id = str(uuid.uuid4())
        db.collection('categories').document(cat_id).set({
            'name': name,
            'image_url': image_url,
            'delivery_type': delivery_type,
            'order': order,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        return cat_id
    except Exception as e:
        print(f"❌ خطأ في إضافة القسم: {e}")
        return None

# === دوال مفاتيح الشحن ===
def get_charge_key(key_code):
    """جلب مفتاح شحن"""
    try:
        if not db:
            return None
        doc = db.collection('charge_keys').document(key_code).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"⚠️ خطأ في جلب مفتاح الشحن: {e}")
        return None

def use_charge_key(key_code, user_id):
    """استخدام مفتاح شحن"""
    try:
        if not db:
            return False
        db.collection('charge_keys').document(key_code).update({
            'used': True,
            'used_by': str(user_id),
            'used_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"❌ خطأ في استخدام مفتاح الشحن: {e}")
        return False

def create_charge_key(key_code, amount):
    """إنشاء مفتاح شحن جديد"""
    try:
        if not db:
            return False
        db.collection('charge_keys').document(key_code).set({
            'amount': float(amount),
            'used': False,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"❌ خطأ في إنشاء مفتاح الشحن: {e}")
        return False

# === دوال الطلبات المعلقة (الدفع) ===
def save_pending_payment(order_id, data):
    """حفظ طلب دفع معلق"""
    try:
        if not db:
            return False
        data['created_at'] = firestore.SERVER_TIMESTAMP
        db.collection('pending_payments').document(order_id).set(data)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ الطلب المعلق: {e}")
        return False

def get_pending_payment(order_id):
    """جلب طلب دفع معلق"""
    try:
        if not db:
            return None
        doc = db.collection('pending_payments').document(order_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"⚠️ خطأ في جلب الطلب المعلق: {e}")
        return None

def update_pending_payment(order_id, data):
    """تحديث طلب دفع معلق"""
    try:
        if not db:
            return False
        db.collection('pending_payments').document(order_id).update(data)
        return True
    except Exception as e:
        print(f"❌ خطأ في تحديث الطلب المعلق: {e}")
        return False

# === دوال السلة ===
def get_user_cart(user_id):
    """جلب سلة المستخدم"""
    try:
        if not db:
            return None
        doc = db.collection('carts').document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"⚠️ خطأ في جلب السلة: {e}")
        return None

def save_user_cart(user_id, cart_data):
    """حفظ سلة المستخدم"""
    try:
        if not db:
            return False
        db.collection('carts').document(str(user_id)).set(cart_data, merge=True)
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ السلة: {e}")
        return False

def clear_user_cart(user_id):
    """مسح سلة المستخدم"""
    try:
        if not db:
            return False
        db.collection('carts').document(str(user_id)).delete()
        return True
    except Exception as e:
        print(f"❌ خطأ في مسح السلة: {e}")
        return False

def get_all_carts():
    """جلب جميع السلات النشطة (للأدمن)"""
    try:
        if not db:
            return []
        carts = []
        for doc in db.collection('carts').stream():
            data = doc.to_dict()
            data['user_id'] = doc.id
            # حساب عدد المنتجات والقيمة الإجمالية
            items = data.get('items', [])
            data['items_count'] = len(items)
            data['total_value'] = sum([float(item.get('price', 0)) for item in items])
            carts.append(data)
        return carts
    except Exception as e:
        print(f"❌ خطأ في جلب السلات: {e}")
        return []

# === دوال سجل عمليات الرصيد (balance_logs) ===
def add_balance_log(user_id, amount, operation_type, description='', order_id='', old_balance=0, new_balance=0):
    """
    إضافة سجل لعملية الرصيد
    
    operation_type: 'credit' (إضافة) أو 'debit' (خصم)
    """
    try:
        if not db:
            return False
        db.collection('balance_logs').add({
            'user_id': str(user_id),
            'amount': float(amount),
            'operation_type': operation_type,  # 'credit' أو 'debit'
            'description': description,
            'order_id': order_id,
            'old_balance': float(old_balance),
            'new_balance': float(new_balance),
            'created_at': firestore.SERVER_TIMESTAMP
        })
        print(f"✅ تم تسجيل عملية الرصيد: {operation_type} {amount} للمستخدم {user_id}")
        return True
    except Exception as e:
        print(f"❌ خطأ في إضافة سجل الرصيد: {e}")
        return False

def get_balance_logs(user_id, limit=50):
    """جلب سجل عمليات الرصيد للمستخدم"""
    try:
        if not db:
            return []
        logs = []
        logs_ref = query_where(db.collection('balance_logs'), 'user_id', '==', str(user_id))
        for doc in logs_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            logs.append(data)
        # ترتيب من الأحدث
        logs.sort(key=lambda x: x.get('created_at', 0) if x.get('created_at') else 0, reverse=True)
        return logs[:limit]
    except Exception as e:
        print(f"❌ خطأ في جلب سجل الرصيد: {e}")
        return []

def get_all_balance_logs(limit=100):
    """جلب جميع سجلات الرصيد (للأدمن)"""
    try:
        if not db:
            return []
        logs = []
        logs_ref = db.collection('balance_logs').limit(limit)
        for doc in logs_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            logs.append(data)
        return logs
    except Exception as e:
        print(f"❌ خطأ في جلب سجلات الرصيد: {e}")
        return []

# === دوال سجل الشحن ===
def add_charge_history(user_id, amount, method='key', order_id=''):
    """إضافة سجل شحن"""
    try:
        if not db:
            return False
        db.collection('charge_history').add({
            'user_id': str(user_id),
            'amount': float(amount),
            'method': method,
            'order_id': order_id,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"❌ خطأ في إضافة سجل الشحن: {e}")
        return False

# === دوال سجل المشتريات ===
def add_purchase_history(buyer_id, seller_id, product_data, order_id=''):
    """إضافة سجل شراء"""
    try:
        if not db:
            return False
        db.collection('purchases').add({
            'buyer_id': str(buyer_id),
            'seller_id': str(seller_id),
            'item_name': product_data.get('item_name', ''),
            'price': float(product_data.get('price', 0)),
            'category': product_data.get('category', ''),
            'order_id': order_id,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        print(f"❌ خطأ في إضافة سجل الشراء: {e}")
        return False

def get_user_purchases(user_id, limit=50):
    """جلب مشتريات المستخدم"""
    try:
        if not db:
            return []
        purchases = []
        purchases_ref = query_where(db.collection('purchases'), 'buyer_id', '==', str(user_id))
        for doc in purchases_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            purchases.append(data)
        # ترتيب من الأحدث
        purchases.sort(key=lambda x: x.get('created_at', 0) if x.get('created_at') else 0, reverse=True)
        return purchases[:limit]
    except Exception as e:
        print(f"❌ خطأ في جلب المشتريات: {e}")
        return []

def get_all_purchases(limit=100):
    """جلب جميع المشتريات (للأدمن)"""
    try:
        if not db:
            return []
        purchases = []
        purchases_ref = db.collection('purchases').limit(limit)
        for doc in purchases_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            purchases.append(data)
        return purchases
    except Exception as e:
        print(f"❌ خطأ في جلب المشتريات: {e}")
        return []

# === دالة تحميل جميع البيانات ===
def load_all_data():
    """تحميل جميع البيانات من Firebase"""
    data = {
        'products': [],
        'users': {},
        'categories': [],
        'charge_keys': {},
        'carts': {},
        'pending_payments': {}
    }
    
    if not db:
        print("⚠️ Firebase غير متاح")
        return data
    
    try:
        print("📥 جاري تحميل البيانات من Firebase...")
        
        # المنتجات
        data['products'] = get_products(sold=False)
        print(f"  ✅ {len(data['products'])} منتج")
        
        # المستخدمين
        for doc in db.collection('users').stream():
            data['users'][doc.id] = doc.to_dict().get('balance', 0.0)
        print(f"  ✅ {len(data['users'])} مستخدم")
        
        # الأقسام
        data['categories'] = get_categories()
        print(f"  ✅ {len(data['categories'])} قسم")
        
        # مفاتيح الشحن
        keys_ref = query_where(db.collection('charge_keys'), 'used', '==', False)
        for doc in keys_ref.stream():
            data['charge_keys'][doc.id] = doc.to_dict()
        print(f"  ✅ {len(data['charge_keys'])} مفتاح شحن")
        
        # السلات
        for doc in db.collection('carts').stream():
            data['carts'][doc.id] = doc.to_dict()
        print(f"  ✅ {len(data['carts'])} سلة")
        
        # الطلبات المعلقة
        pending_ref = query_where(db.collection('pending_payments'), 'status', '==', 'pending')
        for doc in pending_ref.stream():
            data['pending_payments'][doc.id] = doc.to_dict()
        print(f"  ✅ {len(data['pending_payments'])} طلب معلق")
        
        print("🎉 تم تحميل جميع البيانات!")
        
    except Exception as e:
        print(f"❌ خطأ في تحميل البيانات: {e}")
    
    return data

# === دوال للحصول على البيانات مباشرة من Firebase ===

def get_all_products_for_store():
    """جلب جميع المنتجات غير المباعة للمتجر - مباشرة من Firebase"""
    try:
        if not db:
            print("❌ خطأ في جلب المنتجات للمتجر: 'NoneType' object has no attribute 'collection'")
            return []
        products_ref = query_where(db.collection('products'), 'sold', '==', False)
        products = []
        for doc in products_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            products.append(data)
        print(f"✅ تم جلب {len(products)} منتج من Firebase للمتجر")
        return products
    except Exception as e:
        print(f"❌ خطأ في جلب المنتجات للمتجر: {e}")
        return []

def get_sold_products():
    """جلب المنتجات المباعة - مباشرة من Firebase"""
    try:
        if not db:
            print("❌ خطأ في جلب المنتجات المباعة: 'NoneType' object has no attribute 'collection'")
            return []
        products_ref = query_where(db.collection('products'), 'sold', '==', True)
        products = []
        for doc in products_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            products.append(data)
        print(f"✅ تم جلب {len(products)} منتج مباع من Firebase")
        return products
    except Exception as e:
        print(f"❌ خطأ في جلب المنتجات المباعة: {e}")
        return []

def get_all_users():
    """جلب جميع المستخدمين وأرصدتهم - مباشرة من Firebase"""
    try:
        if not db:
            return {}
        users = {}
        for doc in db.collection('users').stream():
            data = doc.to_dict()
            users[doc.id] = data.get('balance', 0.0)
        return users
    except Exception as e:
        print(f"❌ خطأ في جلب المستخدمين: {e}")
        return {}

def get_all_charge_keys():
    """جلب مفاتيح الشحن غير المستخدمة - مباشرة من Firebase"""
    try:
        if not db:
            return {}
        keys = {}
        keys_ref = query_where(db.collection('charge_keys'), 'used', '==', False)
        for doc in keys_ref.stream():
            data = doc.to_dict()
            keys[doc.id] = {
                'amount': data.get('amount', 0),
                'used': data.get('used', False),
                'used_by': data.get('used_by'),
                'created_at': data.get('created_at')
            }
        return keys
    except Exception as e:
        print(f"❌ خطأ في جلب مفاتيح الشحن: {e}")
        return {}

def get_active_orders():
    """جلب الطلبات النشطة - مباشرة من Firebase"""
    try:
        if not db:
            return {}
        orders = {}
        orders_ref = query_where(db.collection('orders'), 'status', '==', 'pending')
        for doc in orders_ref.stream():
            orders[doc.id] = doc.to_dict()
        return orders
    except Exception as e:
        print(f"❌ خطأ في جلب الطلبات النشطة: {e}")
        return {}

def delete_product(product_id):
    """حذف منتج من Firebase"""
    try:
        if not db:
            return False
        db.collection('products').document(product_id).delete()
        print(f"✅ تم حذف المنتج {product_id} من Firebase")
        return True
    except Exception as e:
        print(f"❌ خطأ في حذف المنتج: {e}")
        return False

def update_category(cat_id, data):
    """تحديث قسم في Firebase"""
    try:
        if not db:
            return False
        db.collection('categories').document(cat_id).update(data)
        return True
    except Exception as e:
        print(f"❌ خطأ في تحديث القسم: {e}")
        return False

def delete_category(cat_id):
    """حذف قسم من Firebase"""
    try:
        if not db:
            return False
        db.collection('categories').document(cat_id).delete()
        print(f"✅ تم حذف القسم {cat_id} من Firebase")
        return True
    except Exception as e:
        print(f"❌ خطأ في حذف القسم: {e}")
        return False

def get_category_by_id(cat_id):
    """جلب قسم بالـ ID"""
    try:
        if not db:
            return None
        doc = db.collection('categories').document(cat_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    except Exception as e:
        print(f"⚠️ خطأ في جلب القسم: {e}")
        return None

def get_products_by_category(category_name):
    """جلب المنتجات حسب القسم"""
    try:
        if not db:
            return []
        # أولاً نجلب المنتجات غير المباعة
        products = get_all_products_for_store()
        # ثم نفلتر حسب القسم
        return [p for p in products if p.get('category') == category_name]
    except Exception as e:
        print(f"❌ خطأ في جلب منتجات القسم: {e}")
        return []

def count_products_in_category(category_name):
    """عد المنتجات في قسم معين"""
    products = get_products_by_category(category_name)
    return len(products)

# === دالة جلب البيانات من أي collection ===
def get_collection_data(collection_name, limit=50):
    """جلب البيانات من أي collection في Firebase"""
    try:
        if not db:
            return []
        
        collection_ref = db.collection(collection_name)
        docs = collection_ref.limit(limit).stream()
        
        data = []
        for doc in docs:
            item = doc.to_dict()
            item['id'] = doc.id
            data.append(item)
        
        return data
    except Exception as e:
        print(f"⚠️ خطأ في جلب البيانات من {collection_name}: {e}")
        return []

def get_collection_list():
    """جلب قائمة Collections الموجودة في Firebase"""
    try:
        if not db:
            return []
        
        # جلب جميع Collections
        collections = db.collections()
        return [col.id for col in collections]
    except Exception as e:
        print(f"⚠️ خطأ في جلب قائمة Collections: {e}")
        return []


def get_category_sales_count(category_name):
    """حساب عدد المبيعات لفئة معينة"""
    try:
        if not db:
            return 0
        
        # جلب المنتجات المباعة من هذه الفئة
        products_ref = db.collection('products')
        products_ref = query_where(products_ref, 'category', '==', category_name)
        products_ref = query_where(products_ref, 'status', '==', 'sold')
        
        count = 0
        for doc in products_ref.stream():
            count += 1
        
        return count
    except Exception as e:
        print(f"⚠️ خطأ في حساب مبيعات الفئة: {e}")
        return 0


def get_all_categories_sales():
    """جلب عدد المبيعات لجميع الفئات"""
    try:
        if not db:
            return {}
        
        sales_count = {}
        
        # جلب جميع المنتجات المباعة
        products_ref = query_where(db.collection('products'), 'status', '==', 'sold')
        
        for doc in products_ref.stream():
            product = doc.to_dict()
            category = product.get('category', '')
            if category:
                sales_count[category] = sales_count.get(category, 0) + 1
        
        return sales_count
    except Exception as e:
        print(f"⚠️ خطأ في جلب مبيعات الفئات: {e}")
        return {}

