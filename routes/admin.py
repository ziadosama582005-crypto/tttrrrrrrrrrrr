# -*- coding: utf-8 -*-
"""
نظام لوحة التحكم للمالك
يحتوي على جميع صفحات وAPI الأدمن
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import time
import random
import uuid
import os
import logging
from notifications import notify_owner, notify_all_admins, is_admin_or_owner
from encryption_utils import encrypt_data, decrypt_data
from invoice_generator import send_withdrawal_invoice_email

# 🔒 استيراد نظام Security Logging
try:
    from security_middleware import log_admin_login, log_security_event, SecurityEvent
    SECURITY_LOGGING = True
except ImportError:
    SECURITY_LOGGING = False
    log_admin_login = lambda *args, **kwargs: None

logger = logging.getLogger(__name__)

# إنشاء Blueprint
admin_bp = Blueprint('admin', __name__)

# متغيرات عامة - سيتم تعيينها من init_admin
db = None
bot = None
ADMIN_ID = None
limiter = None
BOT_ACTIVE = False
display_settings = {'categories_columns': 3}

# متغيرات للتحكم في الدخول
admin_login_codes = {}
failed_login_attempts = {}

# ===================== دوال مساعدة =====================

def get_all_products_for_store():
    """جلب جميع المنتجات للمتجر"""
    try:
        products = []
        if db:
            products_ref = db.collection('products')
            for doc in products_ref.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                products.append(data)
        return products
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return []

def get_categories():
    """جلب الأقسام من Firebase"""
    try:
        categories = []
        if db:
            cats_ref = db.collection('categories').order_by('order')
            for doc in cats_ref.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                categories.append(data)
        return categories
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return []

def get_categories_list():
    """جلب قائمة الأقسام"""
    return get_categories()

def get_category_by_id(cat_id):
    """جلب قسم بالـ ID"""
    try:
        if db:
            doc = db.collection('categories').document(cat_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
        return None
    except Exception as e:
        logger.error(f"Error getting category: {e}")
        return None

def update_category(cat_id, update_data):
    """تحديث قسم"""
    try:
        if db:
            db.collection('categories').document(cat_id).update(update_data)
            return True
    except Exception as e:
        logger.error(f"Error updating category: {e}")
    return False

def delete_category(cat_id):
    """حذف قسم"""
    try:
        if db:
            db.collection('categories').document(cat_id).delete()
            return True
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
    return False

def count_products_in_category(category_name):
    """عد المنتجات في قسم"""
    try:
        if db:
            products = db.collection('products').where(filter=FieldFilter('category', '==', category_name)).stream()
            return len(list(products))
        return 0
    except Exception as e:
        logger.error(f"Error counting products: {e}")
        return 0

def add_balance(user_id, amount):
    """إضافة رصيد للمستخدم"""
    try:
        if db:
            from google.cloud import firestore as fs
            user_ref = db.collection('users').document(str(user_id))
            user_doc = user_ref.get()
            if user_doc.exists:
                current_balance = user_doc.to_dict().get('balance', 0)
                user_ref.update({
                    'balance': current_balance + amount,
                    'last_charge_at': fs.SERVER_TIMESTAMP  # تحديث وقت آخر شحن للسحب
                })
            else:
                user_ref.set({
                    'balance': amount,
                    'last_charge_at': fs.SERVER_TIMESTAMP
                })
            return True
    except Exception as e:
        logger.error(f"Error adding balance: {e}")
    return False

def delete_product(product_id):
    """حذف منتج"""
    try:
        if db:
            db.collection('products').document(product_id).delete()
            return True
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
    return False

def query_where(ref, field, op, value):
    """استعلام بشرط"""
    return ref.where(filter=FieldFilter(field, op, value))


# ===================== إعدادات الشريط أعلى الهيدر =====================

def _get_header_settings_doc():
    if not db:
        return None
    return db.collection('settings').document('header')


def _default_header_settings():
    return {
        'enabled': False,
        'text': '',
        'link_url': ''
    }


@admin_bp.route('/admin/header')
def admin_header_settings_page():
    """صفحة تعديل الشريط أعلى الهيدر"""
    if not session.get('is_admin'):
        return redirect('/dashboard')

    settings_data = _default_header_settings()
    try:
        doc_ref = _get_header_settings_doc()
        if doc_ref:
            snap = doc_ref.get()
            if snap.exists:
                settings_data = {**settings_data, **(snap.to_dict() or {})}
    except Exception as e:
        logger.error(f"Error loading header settings: {e}")

    return render_template('admin_header.html', header_settings=settings_data)


@admin_bp.route('/api/admin/get_header_settings')
def api_get_header_settings():
    """جلب إعدادات الشريط أعلى الهيدر"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403

    settings_data = _default_header_settings()
    try:
        doc_ref = _get_header_settings_doc()
        if doc_ref:
            snap = doc_ref.get()
            if snap.exists:
                settings_data = {**settings_data, **(snap.to_dict() or {})}
    except Exception as e:
        logger.error(f"Error getting header settings: {e}")

    return jsonify({'status': 'success', 'data': settings_data})


@admin_bp.route('/api/admin/set_header_settings', methods=['POST'])
def api_set_header_settings():
    """تحديث إعدادات الشريط أعلى الهيدر"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403

    payload = request.json or {}
    enabled = bool(payload.get('enabled', False))
    text = str(payload.get('text', '') or '').strip()
    link_url = str(payload.get('link_url', '') or '').strip()

    # قيود بسيطة لحماية التخزين (بدون تعقيد)
    if len(text) > 200:
        return jsonify({'status': 'error', 'message': 'النص طويل جداً (حد أقصى 200 حرف)'}), 400
    if len(link_url) > 500:
        return jsonify({'status': 'error', 'message': 'الرابط طويل جداً'}), 400

    try:
        doc_ref = _get_header_settings_doc()
        if not doc_ref:
            return jsonify({'status': 'error', 'message': 'Firebase غير متاح'}), 500

        doc_ref.set({
            'enabled': enabled,
            'text': text,
            'link_url': link_url,
            'updated_at': firestore.SERVER_TIMESTAMP
        }, merge=True)

        return jsonify({'status': 'success', 'message': 'تم حفظ إعدادات الشريط'})
    except Exception as e:
        logger.error(f"Error setting header settings: {e}")
        return jsonify({'status': 'error', 'message': 'خطأ في الحفظ'}), 500

# ===================== صفحة الدخول والتحقق =====================

# 🔒 متغير لتتبع طلبات إرسال الكود (حماية إضافية)
code_request_tracker = {}

@admin_bp.route('/api/admin/send_code', methods=['POST'])
def api_send_admin_code():
    """إرسال كود التحقق للمالك"""
    global admin_login_codes, failed_login_attempts, code_request_tracker
    
    try:
        data = request.json
        password = data.get('password', '')
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        
        # 🔒 حماية إضافية: تحديد عدد طلبات الكود لكل IP (3 طلبات كل 10 دقائق)
        current_time = time.time()
        if client_ip in code_request_tracker:
            tracker = code_request_tracker[client_ip]
            # تنظيف الطلبات القديمة (أكثر من 10 دقائق)
            tracker['requests'] = [t for t in tracker['requests'] if current_time - t < 600]
            
            if len(tracker['requests']) >= 3:
                oldest_request = min(tracker['requests'])
                wait_time = int(600 - (current_time - oldest_request))
                return jsonify({
                    'status': 'error',
                    'message': f'⚠️ تم تجاوز حد طلبات الكود. انتظر {wait_time} ثانية'
                })
        else:
            code_request_tracker[client_ip] = {'requests': []}
        
        # التحقق من الحظر بسبب محاولات فاشلة
        if client_ip in failed_login_attempts:
            attempt_data = failed_login_attempts[client_ip]
            if attempt_data.get('blocked_until', 0) > time.time():
                remaining = int(attempt_data['blocked_until'] - time.time())
                return jsonify({
                    'status': 'error',
                    'message': f'⛔ تم حظرك مؤقتاً. حاول بعد {remaining} ثانية'
                })
        
        # التحقق من كلمة المرور
        admin_password = os.environ.get('ADMIN_PASS')
        if not admin_password:
            return jsonify({'status': 'error', 'message': 'النظام غير مُعد بشكل صحيح'}), 503
        
        if password != admin_password:
            # تسجيل المحاولة الفاشلة
            if client_ip not in failed_login_attempts:
                failed_login_attempts[client_ip] = {'count': 0, 'blocked_until': 0}
            
            failed_login_attempts[client_ip]['count'] += 1
            attempts_left = 5 - failed_login_attempts[client_ip]['count']
            
            # حظر بعد 5 محاولات
            if failed_login_attempts[client_ip]['count'] >= 5:
                failed_login_attempts[client_ip]['blocked_until'] = time.time() + 900
                
                # إرسال تنبيه أمني للمالك
                try:
                    alert_msg = f"""
⚠️ *تنبيه أمني!*

محاولات دخول فاشلة متعددة للوحة التحكم!

🌐 *IP:* `{client_ip}`
⏰ *الوقت:* {time.strftime('%Y-%m-%d %H:%M:%S')}
🔒 *الحالة:* تم الحظر لمدة 15 دقيقة
                    """
                    if BOT_ACTIVE and bot:
                        bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
                except Exception as e:
                    print(f"Failed to send security alert: {e}")
                
                return jsonify({
                    'status': 'error',
                    'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'
                })
            
            return jsonify({
                'status': 'error',
                'message': f'❌ كلمة مرور خاطئة! المحاولات المتبقية: {attempts_left}'
            })
        
        # كلمة المرور صحيحة - توليد كود عشوائي
        code = str(random.randint(100000, 999999))
        
        # 🔒 تسجيل طلب الكود للحماية من الإرسال المتكرر
        code_request_tracker[client_ip]['requests'].append(current_time)
        
        # حفظ الكود مع وقت الانتهاء (3 دقائق)
        admin_login_codes = {
            'code': code,
            'created_at': time.time(),
            'expires_at': time.time() + 180,
            'used': False,
            'ip': client_ip
        }
        
        # إرسال الكود للمالك عبر البوت
        try:
            if BOT_ACTIVE and bot:
                code_msg = f"""
🔐 *طلب دخول للوحة التحكم*

📍 *الكود:* `{code}`
⏰ *صالح لمدة:* 3 دقائق
🌐 *IP:* `{client_ip}`
⏱️ *الوقت:* {time.strftime('%Y-%m-%d %H:%M:%S')}

⚠️ *إذا لم تكن أنت، تجاهل هذا الكود!*
                """
                bot.send_message(ADMIN_ID, code_msg, parse_mode='Markdown')
                
                # مسح المحاولات الفاشلة عند النجاح
                if client_ip in failed_login_attempts:
                    del failed_login_attempts[client_ip]
                
                return jsonify({'status': 'success', 'message': 'تم إرسال الكود'})
            else:
                return jsonify({
                    'status': 'error',
                    'message': '❌ البوت غير متصل! لا يمكن إرسال الكود'
                })
        except Exception as e:
            print(f"Error sending code: {e}")
            return jsonify({
                'status': 'error',
                'message': '❌ فشل إرسال الكود للبوت'
            })
            
    except Exception as e:
        print(f"Error in send_code: {e}")
        return jsonify({'status': 'error', 'message': 'خطأ في السيرفر'})

@admin_bp.route('/api/admin/verify_code', methods=['POST'])
def api_verify_admin_code():
    """التحقق من كود الدخول"""
    global admin_login_codes
    
    try:
        data = request.json
        code = data.get('code', '').strip()
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        
        # التحقق من وجود كود نشط
        if not admin_login_codes or not admin_login_codes.get('code'):
            return jsonify({
                'status': 'error',
                'message': '❌ لا يوجد كود نشط. اطلب كود جديد'
            })
        
        # التحقق من انتهاء الصلاحية
        if time.time() > admin_login_codes.get('expires_at', 0):
            admin_login_codes = {}
            return jsonify({
                'status': 'error',
                'message': '⏰ انتهت صلاحية الكود! اطلب كود جديد'
            })
        
        # التحقق من استخدام الكود مسبقاً
        if admin_login_codes.get('used'):
            return jsonify({
                'status': 'error',
                'message': '❌ تم استخدام هذا الكود مسبقاً'
            })
        
        # التحقق من صحة الكود
        if code != admin_login_codes.get('code'):
            return jsonify({
                'status': 'error',
                'message': '❌ كود خاطئ!'
            })
        
        # الكود صحيح - تسجيل الدخول
        admin_login_codes['used'] = True
        session['is_admin'] = True
        
        # 🔒 تسجيل دخول الأدمن في سجل الأمان
        if SECURITY_LOGGING:
            log_admin_login(ADMIN_ID, client_ip)
        
        # إرسال إشعار بنجاح الدخول
        try:
            if BOT_ACTIVE and bot:
                success_msg = f"""
✅ *تم تسجيل الدخول بنجاح!*

🌐 *IP:* `{client_ip}`
⏰ *الوقت:* {time.strftime('%Y-%m-%d %H:%M:%S')}
                """
                bot.send_message(ADMIN_ID, success_msg, parse_mode='Markdown')
        except:
            pass
        
        # مسح الكود
        admin_login_codes = {}
        
        return jsonify({'status': 'success', 'message': 'تم التحقق بنجاح'})
        
    except Exception as e:
        print(f"Error in verify_code: {e}")
        return jsonify({'status': 'error', 'message': 'خطأ في السيرفر'})

@admin_bp.route('/logout_admin')
def logout_admin():
    """تسجيل خروج الأدمن"""
    session.pop('is_admin', None)
    return redirect('/dashboard')

# ===================== صفحات لوحة التحكم =====================

@admin_bp.route('/admin/products')
def admin_products():
    """صفحة إدارة المنتجات"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_products_new.html', admin_id=ADMIN_ID, active_page='products')

@admin_bp.route('/admin/categories')
def admin_categories():
    """صفحة إدارة الأقسام"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_categories_new.html', active_page='categories')

@admin_bp.route('/admin/invoices')
def admin_invoices():
    """صفحة عرض الفواتير والمعاملات"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_invoices_new.html', active_page='invoices')

@admin_bp.route('/admin/customers')
def admin_customers():
    """صفحة إدارة العملاء"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_customers.html', active_page='customers')

@admin_bp.route('/admin/orders')
def admin_orders():
    """صفحة إدارة الطلبات"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_orders.html', active_page='orders')

@admin_bp.route('/admin/balance-logs')
def admin_balance_logs_page():
    """صفحة سجل الرصيد"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_balance_logs.html', active_page='balance_logs')

@admin_bp.route('/admin/carts')
def admin_carts_page():
    """صفحة السلات النشطة"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_carts.html', active_page='carts')

@admin_bp.route('/admin/charge-keys')
def admin_charge_keys():
    """صفحة كروت الشحن"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_charge_keys.html', active_page='charge_keys')

# ===================== API إحصائيات لوحة التحكم =====================

@admin_bp.route('/api/admin/dashboard_stats')
def api_dashboard_stats():
    """جلب إحصائيات لوحة التحكم الكاملة"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        stats = {
            'total_products': 0,
            'available_products': 0,
            'sold_products': 0,
            'total_users': 0,
            'total_orders': 0,
            'pending_orders': 0,
            'categories': 0,
            'pending_payments': 0,
            'completed_payments': 0,
            'total_revenue': 0,
            'total_balance': 0,
            'active_carts': 0,
            'active_keys': 0,
            'used_keys': 0,
            'pending_invoices': 0,
            'recent_orders': [],
            'users_list': [],
            'top_cart_products': []
        }
        
        if db:
            # المنتجات - نستخدم نفس query المستخدمة في المتجر للحصول على نتائج متطابقة
            try:
                # المنتجات المتاحة: sold == False بالضبط (نفس query المتجر)
                available_query = query_where(db.collection('products'), 'sold', '==', False)
                available_products = list(available_query.stream())
                stats['available_products'] = len(available_products)
                
                # المنتجات المباعة: sold == True
                sold_query = query_where(db.collection('products'), 'sold', '==', True)
                sold_products = list(sold_query.stream())
                stats['sold_products'] = len(sold_products)
                
                # إجمالي المنتجات = متاح + مباع
                stats['total_products'] = stats['available_products'] + stats['sold_products']
                
                logger.info(f"Dashboard stats: available={stats['available_products']}, sold={stats['sold_products']}, total={stats['total_products']}")
            except Exception as e:
                logger.error(f"Error getting products: {e}")
            
            # المستخدمين والأرصدة
            try:
                users = list(db.collection('users').stream())
                stats['total_users'] = len(users)
                users_list = []
                total_balance = 0
                for u in users:
                    u_data = u.to_dict()
                    balance = u_data.get('balance', 0)
                    total_balance += balance
                    users_list.append({
                        'id': u.id,
                        'name': u_data.get('name', u_data.get('telegram_name', 'مستخدم')),
                        'balance': balance,
                        'username': u_data.get('username', '')
                    })
                stats['total_balance'] = total_balance
                stats['users_list'] = users_list
            except Exception as e:
                logger.error(f"Error getting users: {e}")
            
            # الطلبات
            try:
                orders_ref = db.collection('orders')
                all_orders = list(orders_ref.stream())
                stats['total_orders'] = len(all_orders)
                
                # حساب الإيرادات وآخر الطلبات
                recent_orders = []
                total_revenue = 0
                pending_count = 0
                
                # جلب آخر 20 طلب
                recent_docs = list(orders_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(20).stream())
                for doc in recent_docs:
                    data = doc.to_dict()
                    price = data.get('price', 0)
                    total_revenue += price
                    
                    if data.get('status') in ['pending', 'processing']:
                        pending_count += 1
                    
                    recent_orders.append({
                        'id': doc.id[:8],
                        'item_name': data.get('item_name', 'منتج'),
                        'price': price,
                        'buyer_name': data.get('buyer_name', 'مشتري'),
                        'buyer_id': data.get('buyer_id', ''),
                        'created_at': str(data.get('created_at', ''))
                    })
                
                stats['total_revenue'] = sum([o.to_dict().get('price', 0) for o in all_orders])
                stats['recent_orders'] = recent_orders
                stats['pending_orders'] = pending_count
            except Exception as e:
                logger.error(f"Error getting orders: {e}")
            
            # الأقسام
            try:
                categories = list(db.collection('categories').stream())
                stats['categories'] = len(categories)
            except:
                pass
            
            # كروت الشحن
            try:
                keys = list(db.collection('charge_keys').stream())
                active_keys = 0
                used_keys = 0
                for k in keys:
                    if k.to_dict().get('used', False):
                        used_keys += 1
                    else:
                        active_keys += 1
                stats['active_keys'] = active_keys
                stats['used_keys'] = used_keys
            except:
                pass
            
            # الفواتير المعلقة
            try:
                invoices = list(db.collection('merchant_invoices').where(filter=FieldFilter('status', '==', 'pending')).stream())
                stats['pending_invoices'] = len(invoices)
            except:
                pass
            
            # طلبات الدفع
            try:
                pending = list(db.collection('pending_payments').where(filter=FieldFilter('status', '==', 'pending')).stream())
                stats['pending_payments'] = len(pending)
                
                completed = list(db.collection('pending_payments').where(filter=FieldFilter('status', '==', 'completed')).stream())
                stats['completed_payments'] = len(completed)
            except:
                pass
            
            # السلات النشطة
            try:
                carts = list(db.collection('carts').stream())
                stats['active_carts'] = len(carts)
            except:
                pass
            
            # إحصائيات السلة - أكثر المنتجات إضافة
            try:
                cart_stats = list(db.collection('cart_stats').order_by('add_to_cart_count', direction=firestore.Query.DESCENDING).limit(10).stream())
                top_cart_products = []
                for stat in cart_stats:
                    stat_data = stat.to_dict()
                    # جلب اسم المنتج
                    try:
                        prod_doc = db.collection('products').document(stat.id).get()
                        prod_name = prod_doc.to_dict().get('item_name', 'منتج') if prod_doc.exists else 'محذوف'
                    except:
                        prod_name = 'غير معروف'
                    
                    top_cart_products.append({
                        'product_id': stat.id,
                        'name': prod_name,
                        'add_count': stat_data.get('add_to_cart_count', 0),
                        'purchase_count': stat_data.get('purchase_count', 0)
                    })
                stats['top_cart_products'] = top_cart_products
            except:
                pass
        
        return jsonify({
            'status': 'success',
            'stats': stats
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب إحصائيات لوحة التحكم: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ===================== API الفواتير =====================

@admin_bp.route('/api/admin/get_invoices')
def api_get_invoices():
    """جلب جميع الفواتير والمعاملات المالية"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        # 1️⃣ طلبات الدفع (pending_payments)
        pending_payments_list = []
        try:
            pending_ref = db.collection('pending_payments').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in pending_ref.stream():
                data = doc.to_dict()
                user_name = 'غير معروف'
                user_id = data.get('user_id', '')
                
                # جلب رقم الجوال من عدة مصادر
                user_phone = data.get('payer_phone', '') or data.get('customer_phone', '') or data.get('phone', '')
                
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                        # إذا لم يكن هناك رقم، جرب من بيانات المستخدم
                        if not user_phone:
                            user_phone = user_data.get('phone', '')
                except:
                    pass
                
                pending_payments_list.append({
                    'id': doc.id,
                    'order_id': data.get('order_id', doc.id),
                    'user_id': user_id,
                    'user_name': user_name,
                    'user_phone': user_phone,
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
        
        # 5️⃣ المنتجات المباعة والمتاحة
        sold_products_list = []
        available_products_list = []
        try:
            products_ref = db.collection('products')
            for doc in products_ref.stream():
                data = doc.to_dict()
                
                buyer_name = data.get('buyer_name', '')
                buyer_id = data.get('buyer_id', '')
                
                if data.get('sold') and buyer_id:
                    if not buyer_name or buyer_name == '':
                        try:
                            buyer_doc = db.collection('users').document(str(buyer_id)).get()
                            if buyer_doc.exists:
                                buyer_data = buyer_doc.to_dict()
                                buyer_name = buyer_data.get('name') or buyer_data.get('username') or buyer_data.get('telegram_name') or ''
                        except Exception as e:
                            print(f"⚠️ خطأ في جلب بيانات المشتري {buyer_id}: {e}")
                    
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
        
        # 6️⃣ سجل عمليات الرصيد (balance_logs)
        balance_logs_list = []
        try:
            logs_ref = db.collection('balance_logs').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100)
            for doc in logs_ref.stream():
                data = doc.to_dict()
                user_name = 'غير معروف'
                user_id = data.get('user_id', '')
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                except:
                    pass
                
                op_type = data.get('operation_type', '')
                balance_logs_list.append({
                    'id': doc.id,
                    'user_id': user_id,
                    'user_name': user_name,
                    'amount': data.get('amount', 0),
                    'operation_type': op_type,
                    'type': 'إضافة رصيد' if op_type == 'credit' else 'خصم رصيد',
                    'description': data.get('description', ''),
                    'order_id': data.get('order_id', ''),
                    'old_balance': data.get('old_balance', 0),
                    'new_balance': data.get('new_balance', 0),
                    'created_at': str(data.get('created_at', ''))
                })
        except Exception as e:
            print(f"⚠️ خطأ في جلب balance_logs: {e}")
        
        # 7️⃣ إحصائيات
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
            'total_charged': sum([c['amount'] for c in charge_history_list]),
            'total_balance_logs': len(balance_logs_list),
            'total_credits': sum([l['amount'] for l in balance_logs_list if l['operation_type'] == 'credit']),
            'total_debits': sum([l['amount'] for l in balance_logs_list if l['operation_type'] == 'debit'])
        }
        
        return jsonify({
            'status': 'success',
            'pending_payments': pending_payments_list,
            'merchant_invoices': merchant_invoices_list,
            'charge_history': charge_history_list,
            'orders': orders_list,
            'sold_products': sold_products_list,
            'available_products': available_products_list,
            'balance_logs': balance_logs_list,
            'stats': stats
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب الفواتير: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})

# ===================== API سجل عمليات الرصيد (balance_logs) =====================

@admin_bp.route('/api/admin/get_balance_logs')
def api_get_balance_logs():
    """جلب جميع سجلات عمليات الرصيد"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        balance_logs_list = []
        
        if db:
            # جلب بدون order_by لتجنب مشكلة Index
            logs_ref = db.collection('balance_logs').limit(500)
            all_logs = []
            
            for doc in logs_ref.stream():
                data = doc.to_dict()
                user_id = data.get('user_id', '')
                
                # تحويل created_at لرقم للترتيب
                created_at = data.get('created_at')
                timestamp = 0
                if created_at:
                    if hasattr(created_at, 'timestamp'):
                        timestamp = created_at.timestamp()
                    elif hasattr(created_at, 'seconds'):
                        timestamp = created_at.seconds
                    elif isinstance(created_at, (int, float)):
                        timestamp = created_at
                
                all_logs.append({
                    'id': doc.id,
                    'user_id': user_id,
                    'amount': data.get('amount', 0),
                    'operation_type': data.get('operation_type', ''),
                    'description': data.get('description', ''),
                    'order_id': data.get('order_id', ''),
                    'old_balance': data.get('old_balance', 0),
                    'new_balance': data.get('new_balance', 0),
                    'created_at': str(data.get('created_at', '')),
                    'timestamp': timestamp
                })
            
            # ترتيب من الأحدث
            all_logs.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            
            # أخذ أول 200 وجلب أسماء المستخدمين
            for log in all_logs[:200]:
                user_name = 'غير معروف'
                user_id = log.get('user_id', '')
                
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                except:
                    pass
                
                log['user_name'] = user_name
                del log['timestamp']  # حذف الحقل المؤقت
                balance_logs_list.append(log)
        
        # إحصائيات
        total_credits = sum([l['amount'] for l in balance_logs_list if l['operation_type'] == 'credit'])
        total_debits = sum([l['amount'] for l in balance_logs_list if l['operation_type'] == 'debit'])
        
        return jsonify({
            'status': 'success',
            'balance_logs': balance_logs_list,
            'stats': {
                'total_logs': len(balance_logs_list),
                'total_credits': total_credits,
                'total_debits': total_debits,
                'net_balance': total_credits - total_debits
            }
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب سجلات الرصيد: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


@admin_bp.route('/api/admin/get_user_history')
def api_get_user_history():
    """جلب سجل مستخدم معين (الشحنات والرصيد)"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    user_id = request.args.get('user_id', '').strip()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'يرجى إدخال معرف المستخدم'})
    
    try:
        result = {
            'user': None,
            'charges': [],
            'withdrawals': [],
            'balance_logs': []
        }
        
        if db:
            # 1. بيانات المستخدم
            user_doc = db.collection('users').document(str(user_id)).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                result['user'] = {
                    'id': user_id,
                    'name': user_data.get('name', 'غير معروف'),
                    'balance': user_data.get('balance', 0),
                    'last_charge_at': str(user_data.get('last_charge_at', ''))
                }
            else:
                return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'})
            
            # 2. سجل الشحنات (نبحث بـ string و number)
            charges_ref = db.collection('charge_history').where(filter=FieldFilter('user_id', '==', str(user_id)))
            for doc in charges_ref.stream():
                data = doc.to_dict()
                # تحويل timestamp لرقم
                ts = data.get('timestamp', 0)
                if hasattr(ts, 'timestamp'):
                    ts = ts.timestamp()
                elif hasattr(ts, 'seconds'):
                    ts = ts.seconds
                elif not isinstance(ts, (int, float)):
                    ts = 0
                
                result['charges'].append({
                    'id': doc.id,
                    'amount': data.get('amount', 0),
                    'method': data.get('method', 'غير محدد'),
                    'date': data.get('date', ''),
                    'timestamp': ts,
                    'type': data.get('type', '')
                })
            
            # البحث أيضاً بـ number إذا لم نجد
            if len(result['charges']) == 0:
                try:
                    charges_ref2 = db.collection('charge_history').where(filter=FieldFilter('user_id', '==', int(user_id)))
                    for doc in charges_ref2.stream():
                        data = doc.to_dict()
                        # تحويل timestamp لرقم
                        ts = data.get('timestamp', 0)
                        if hasattr(ts, 'timestamp'):
                            ts = ts.timestamp()
                        elif hasattr(ts, 'seconds'):
                            ts = ts.seconds
                        elif not isinstance(ts, (int, float)):
                            ts = 0
                        
                        result['charges'].append({
                            'id': doc.id,
                            'amount': data.get('amount', 0),
                            'method': data.get('method', 'غير محدد'),
                            'date': data.get('date', ''),
                            'timestamp': ts,
                            'type': data.get('type', '')
                        })
                except:
                    pass
            
            # 2.1 جلب الشحنات من pending_payments المكتملة (للشحنات القديمة)
            try:
                payments_ref = db.collection('pending_payments').where(filter=FieldFilter('user_id', '==', str(user_id))).where(filter=FieldFilter('status', '==', 'completed'))
                for doc in payments_ref.stream():
                    data = doc.to_dict()
                    # تحقق أنها غير مضافة مسبقاً
                    if not any(c.get('id') == doc.id for c in result['charges']):
                        completed_at = data.get('completed_at')
                        timestamp = 0
                        date_str = ''
                        if completed_at:
                            if hasattr(completed_at, 'timestamp'):
                                timestamp = completed_at.timestamp()
                            try:
                                from datetime import datetime
                                date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M') if timestamp else ''
                            except:
                                pass
                        
                        result['charges'].append({
                            'id': doc.id,
                            'amount': data.get('amount', 0),
                            'method': 'edfapay',
                            'date': date_str,
                            'timestamp': timestamp,
                            'type': 'payment'
                        })
            except Exception as e:
                print(f"خطأ في جلب pending_payments: {e}")
            
            # ترتيب حسب الوقت (الأحدث أولاً)
            result['charges'].sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            
            # 3. طلبات السحب
            try:
                withdrawals_ref = db.collection('withdrawal_requests').where(filter=FieldFilter('user_id', '==', str(user_id)))
                for doc in withdrawals_ref.stream():
                    data = doc.to_dict()
                    result['withdrawals'].append({
                        'id': doc.id,
                        'amount': data.get('amount', 0),
                        'net_amount': data.get('net_amount', 0),
                        'fee_percent': data.get('fee_percent', 0),
                        'method': data.get('method', ''),
                        'status': data.get('status', 'pending'),
                        'created_at': str(data.get('created_at', ''))
                    })
            except:
                pass
            
            # 4. سجل الرصيد (آخر 50)
            try:
                logs_ref = db.collection('balance_logs').where(filter=FieldFilter('user_id', '==', str(user_id))).limit(50)
                for doc in logs_ref.stream():
                    data = doc.to_dict()
                    result['balance_logs'].append({
                        'amount': data.get('amount', 0),
                        'operation_type': data.get('operation_type', ''),
                        'description': data.get('description', ''),
                        'old_balance': data.get('old_balance', 0),
                        'new_balance': data.get('new_balance', 0),
                        'created_at': str(data.get('created_at', ''))
                    })
            except:
                pass
        
        return jsonify({
            'status': 'success',
            'data': result,
            'stats': {
                'total_charges': len(result['charges']),
                'total_charged': sum([c['amount'] for c in result['charges']]),
                'total_withdrawals': len(result['withdrawals'])
            }
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب سجل المستخدم: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})


# ===================== API السلات النشطة (carts) =====================

@admin_bp.route('/api/admin/get_carts')
def api_get_carts():
    """جلب جميع السلات النشطة"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        carts_list = []
        
        if db:
            for doc in db.collection('carts').stream():
                data = doc.to_dict()
                user_id = doc.id
                user_name = 'غير معروف'
                
                # جلب اسم المستخدم
                try:
                    user_doc = db.collection('users').document(str(user_id)).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        user_name = user_data.get('name', user_data.get('telegram_name', f'مستخدم {user_id}'))
                except:
                    pass
                
                items = data.get('items', [])
                total_value = sum([float(item.get('price', 0)) for item in items])
                
                carts_list.append({
                    'user_id': user_id,
                    'user_name': user_name,
                    'items_count': len(items),
                    'items': items,
                    'total_value': total_value,
                    'status': data.get('status', 'active'),
                    'created_at': str(data.get('created_at', '')),
                    'expires_at': str(data.get('expires_at', ''))
                })
        
        # إحصائيات
        total_carts = len(carts_list)
        total_items = sum([c['items_count'] for c in carts_list])
        total_value = sum([c['total_value'] for c in carts_list])
        
        return jsonify({
            'status': 'success',
            'carts': carts_list,
            'stats': {
                'total_carts': total_carts,
                'total_items': total_items,
                'total_value': total_value
            }
        })
        
    except Exception as e:
        print(f"❌ خطأ في جلب السلات: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)})

# ===================== API المنتجات =====================

@admin_bp.route('/api/admin/get_products')
def api_get_products():
    """جلب جميع المنتجات"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        available = []
        sold = []
        
        if db:
            # استخدام نفس query المتجر للحصول على نتائج متطابقة
            # المنتجات المتاحة: sold == False بالضبط
            available_query = query_where(db.collection('products'), 'sold', '==', False)
            for doc in available_query.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                available.append(data)
            
            # المنتجات المباعة: sold == True
            sold_query = query_where(db.collection('products'), 'sold', '==', True)
            for doc in sold_query.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                sold.append(data)
            
            logger.info(f"Products API: Available={len(available)}, Sold={len(sold)}")
        
        return jsonify({
            'status': 'success',
            'available': available,
            'sold': sold
        })
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/admin/add_product_new', methods=['POST'])
def api_add_product_new():
    """إضافة منتج جديد"""
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
        
        if delivery_type not in ['instant', 'manual']:
            delivery_type = 'instant'
        
        if not name or price <= 0 or not category:
            return jsonify({'status': 'error', 'message': 'بيانات ناقصة (الاسم، السعر، الفئة)'})
        
        if delivery_type == 'instant' and not hidden_data:
            return jsonify({'status': 'error', 'message': 'البيانات السرية مطلوبة للتسليم الفوري'})
        
        if delivery_type == 'manual' and not buyer_instructions:
            return jsonify({'status': 'error', 'message': 'يجب تحديد ما تحتاجه من المشتري'})
        
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
        
        if db:
            db.collection('products').document(product_id).set(product_data)
            print(f"✅ تم حفظ المنتج في Firebase: {name} (التسليم: {delivery_type})")
        
        return jsonify({'status': 'success', 'product_id': product_id})
        
    except Exception as e:
        logger.error(f"Error adding product: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/admin/delete_product', methods=['POST'])
def api_delete_product():
    """حذف منتج"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        product_id = data.get('product_id')
        
        if not product_id:
            return jsonify({'status': 'error', 'message': 'معرف المنتج مطلوب'})
        
        delete_product(product_id)
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/add_balance', methods=['POST'])
def api_add_balance():
    """شحن رصيد مستخدم"""
    if not session.get('is_admin'):
        return {'status': 'error', 'message': 'غير مصرح!'}
    
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount'))
    
    if not user_id or amount <= 0:
        return {'status': 'error', 'message': 'بيانات غير صحيحة'}
    
    add_balance(user_id, amount)
    
    try:
        if bot:
            bot.send_message(int(user_id), f"🎉 تم شحن رصيدك بمبلغ {amount} ريال!")
    except:
        pass
    
    return {'status': 'success'}

@admin_bp.route('/api/add_product', methods=['POST'])
def api_add_product():
    """إضافة منتج"""
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
        
        if not name or not price or not hidden_data:
            return {'status': 'error', 'message': 'بيانات غير كاملة'}
        
        new_id = str(uuid.uuid4())
        item = {
            'id': new_id,
            'item_name': name,
            'price': float(price),
            'seller_id': str(ADMIN_ID),
            'seller_name': 'المالك',
            'hidden_data': hidden_data,
            'category': category,
            'details': details,
            'image_url': image,
            'sold': False,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        
        db.collection('products').document(new_id).set(item)
        print(f"✅ تم حفظ المنتج {new_id} في Firestore: {name}")
        
        try:
            if bot:
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

@admin_bp.route('/api/generate_keys', methods=['POST'])
def api_generate_keys():
    """توليد مفاتيح شحن"""
    if not session.get('is_admin'):
        return {'status': 'error', 'message': 'غير مصرح!'}
    
    try:
        data = request.json
        amount = float(data.get('amount'))
        count = int(data.get('count', 1))
        
        if amount <= 0 or count <= 0 or count > 100:
            return {'status': 'error', 'message': 'أرقام غير صحيحة'}
        
        generated_keys = []
        batch = db.batch()
        
        for _ in range(count):
            key_code = f"KEY-{random.randint(10000, 99999)}-{random.randint(1000, 9999)}"
            
            key_data = {
                'amount': amount,
                'used': False,
                'used_by': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            doc_ref = db.collection('charge_keys').document(key_code)
            batch.set(doc_ref, key_data)
            
            generated_keys.append(key_code)
            
        batch.commit()
        
        return {'status': 'success', 'keys': generated_keys}

    except Exception as e:
        print(f"Error generating keys: {e}")
        return {'status': 'error', 'message': f'فشل التوليد: {str(e)}'}

# ===================== API الأقسام =====================

@admin_bp.route('/api/admin/get_categories', methods=['GET'])
def api_get_categories():
    """جلب قائمة الأقسام"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        all_products = get_all_products_for_store()
        category_counts = {}
        for item in all_products:
            cat = item.get('category', '')
            if cat:
                category_counts[cat] = category_counts.get(cat, 0) + 1
        
        categories = get_categories_list()
        
        result = []
        for cat in categories:
            cat_data = cat.copy()
            cat_data['product_count'] = category_counts.get(cat['name'], 0)
            result.append(cat_data)
        
        return jsonify({'status': 'success', 'categories': result})
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/admin/add_category', methods=['POST'])
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
        
        current_categories = get_categories()
        
        for cat in current_categories:
            if cat['name'] == name:
                return jsonify({'status': 'error', 'message': 'هذا القسم موجود مسبقاً'})
        
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
        
        if db:
            db.collection('categories').document(cat_id).set(new_category)
            print(f"✅ تم حفظ القسم في Firebase: {name} ({delivery_type})")
        
        return jsonify({'status': 'success', 'category': new_category})
        
    except Exception as e:
        logger.error(f"Error adding category: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/admin/update_category', methods=['POST'])
def api_update_category():
    """تعديل قسم"""
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
        
        cat_found = get_category_by_id(cat_id)
        
        if not cat_found:
            return jsonify({'status': 'error', 'message': 'القسم غير موجود'})
        
        old_name = cat_found.get('name', '')
        
        update_data = {}
        if new_name:
            update_data['name'] = new_name
        if new_image:
            update_data['image_url'] = new_image
        if new_delivery_type in ['instant', 'manual']:
            update_data['delivery_type'] = new_delivery_type
        
        update_category(cat_id, update_data)
        
        if old_name and new_name and old_name != new_name:
            all_products = get_all_products_for_store()
            for item in all_products:
                if item.get('category') == old_name:
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

@admin_bp.route('/api/admin/delete_category', methods=['POST'])
def api_delete_category():
    """حذف قسم"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        cat_id = data.get('id')
        
        if not cat_id:
            return jsonify({'status': 'error', 'message': 'معرف القسم مطلوب'})
        
        cat_found = get_category_by_id(cat_id)
        
        if not cat_found:
            return jsonify({'status': 'error', 'message': 'القسم غير موجود'})
        
        product_count = count_products_in_category(cat_found.get('name', ''))
        
        if product_count > 0:
            return jsonify({
                'status': 'error', 
                'message': f'لا يمكن حذف القسم - يوجد {product_count} منتج فيه'
            })
        
        delete_category(cat_id)
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ، حاول لاحقاً'})

@admin_bp.route('/api/admin/reorder_categories', methods=['POST'])
def api_reorder_categories():
    """إعادة ترتيب الأقسام"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        new_order = data.get('order', [])
        
        if not new_order:
            return jsonify({'status': 'error', 'message': 'الترتيب مطلوب'})
        
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

@admin_bp.route('/api/categories', methods=['GET'])
def api_public_categories():
    """جلب الأقسام للعرض العام"""
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

# ===================== إعدادات العرض =====================

@admin_bp.route('/api/admin/get_display_settings', methods=['GET'])
def api_get_display_settings():
    """جلب إعدادات العرض"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    return jsonify({
        'status': 'success',
        'categories_columns': display_settings.get('categories_columns', 3)
    })

@admin_bp.route('/api/admin/set_display_settings', methods=['POST'])
def api_set_display_settings():
    """تعديل إعدادات العرض"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'})
    
    try:
        data = request.json
        cols = data.get('categories_columns')
        
        if cols and cols in [2, 3, 4]:
            display_settings['categories_columns'] = cols
            
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


# ===================== APIs العملاء =====================

@admin_bp.route('/api/admin/get_customers')
def api_get_customers():
    """جلب جميع العملاء مع إحصائياتهم"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        customers = []
        total_balance = 0
        total_orders = 0
        total_spent = 0
        
        if db:
            # جلب المستخدمين
            users_ref = db.collection('users').stream()
            
            for doc in users_ref:
                user_data = doc.to_dict()
                user_id = doc.id
                
                # حساب عدد الطلبات وإجمالي المشتريات
                orders_count = 0
                user_spent = 0
                last_activity = None
                
                try:
                    orders = db.collection('orders').where(filter=FieldFilter('buyer_id', '==', user_id)).stream()
                    for order in orders:
                        order_data = order.to_dict()
                        orders_count += 1
                        user_spent += float(order_data.get('price', 0))
                        
                        order_date = order_data.get('created_at')
                        if order_date and (not last_activity or order_date > last_activity):
                            last_activity = order_date
                except:
                    pass
                
                balance = float(user_data.get('balance', 0))
                total_balance += balance
                total_orders += orders_count
                total_spent += user_spent
                
                customers.append({
                    'id': user_id,
                    'user_id': user_id,
                    'name': user_data.get('name') or user_data.get('username') or user_data.get('first_name'),
                    'username': user_data.get('username'),
                    'first_name': user_data.get('first_name'),
                    'balance': balance,
                    'orders_count': orders_count,
                    'total_spent': user_spent,
                    'last_activity': last_activity.isoformat() if last_activity else None,
                    'has_2fa': user_data.get('has_2fa', False)
                })
        
        return jsonify({
            'status': 'success',
            'customers': customers,
            'stats': {
                'total_customers': len(customers),
                'total_balance': total_balance,
                'total_orders': total_orders,
                'total_spent': total_spent
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting customers: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/get_customer_details')
def api_get_customer_details():
    """جلب تفاصيل عميل معين"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'status': 'error', 'message': 'معرف المستخدم مطلوب'})
    
    try:
        if not db:
            return jsonify({'status': 'error', 'message': 'قاعدة البيانات غير متاحة'})
        
        # جلب بيانات المستخدم
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'})
        
        user_data = user_doc.to_dict()
        
        # جلب الطلبات
        orders = []
        total_spent = 0
        try:
            orders_ref = db.collection('orders').where(filter=FieldFilter('buyer_id', '==', user_id)).stream()
            for doc in orders_ref:
                order = doc.to_dict()
                order['id'] = doc.id
                if order.get('created_at'):
                    order['created_at'] = order['created_at'].isoformat() if hasattr(order['created_at'], 'isoformat') else str(order['created_at'])
                orders.append(order)
                total_spent += float(order.get('price', 0))
        except:
            pass
        
        # جلب سجل الرصيد
        balance_logs = []
        try:
            logs_ref = db.collection('balance_logs').where(filter=FieldFilter('user_id', '==', user_id)).order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
            for doc in logs_ref:
                log = doc.to_dict()
                log['id'] = doc.id
                if log.get('created_at'):
                    log['created_at'] = log['created_at'].isoformat() if hasattr(log['created_at'], 'isoformat') else str(log['created_at'])
                balance_logs.append(log)
        except:
            pass
        
        customer = {
            'id': user_id,
            'user_id': user_id,
            'name': user_data.get('name') or user_data.get('username') or user_data.get('first_name'),
            'username': user_data.get('username'),
            'first_name': user_data.get('first_name'),
            'balance': float(user_data.get('balance', 0)),
            'orders_count': len(orders),
            'total_spent': total_spent,
            'has_2fa': user_data.get('has_2fa', False),
            'phone_verified': user_data.get('phone_verified', False),
            'verified_phone': user_data.get('verified_phone') or user_data.get('phone', ''),
            'orders': orders,
            'balance_logs': balance_logs
        }
        
        return jsonify({
            'status': 'success',
            'customer': customer
        })
        
    except Exception as e:
        logger.error(f"Error getting customer details: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== APIs الطلبات =====================

@admin_bp.route('/api/admin/get_orders')
def api_get_orders():
    """جلب جميع الطلبات"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        orders = []
        completed = 0
        pending = 0
        revenue = 0
        
        if db:
            orders_ref = db.collection('orders').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
            
            for doc in orders_ref:
                order = doc.to_dict()
                order['id'] = doc.id
                
                if order.get('created_at'):
                    order['created_at'] = order['created_at'].isoformat() if hasattr(order['created_at'], 'isoformat') else str(order['created_at'])
                
                price = float(order.get('price', 0))
                revenue += price
                
                if order.get('status') == 'completed':
                    completed += 1
                else:
                    pending += 1
                
                orders.append(order)
        
        return jsonify({
            'status': 'success',
            'orders': orders,
            'stats': {
                'total': len(orders),
                'completed': completed,
                'pending': pending,
                'revenue': revenue
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/complete_order', methods=['POST'])
def api_complete_order():
    """إكمال طلب يدوي"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        data = request.json
        order_id = data.get('order_id')
        
        if not order_id or not db:
            return jsonify({'status': 'error', 'message': 'بيانات ناقصة'})
        
        # تحديث حالة الطلب
        order_ref = db.collection('orders').document(order_id)
        order_doc = order_ref.get()
        
        if not order_doc.exists:
            return jsonify({'status': 'error', 'message': 'الطلب غير موجود'})
        
        order_ref.update({
            'status': 'completed',
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        
        # إشعار المشتري
        order_data = order_doc.to_dict()
        buyer_id = order_data.get('buyer_id')
        
        if bot and buyer_id:
            try:
                msg = f"✅ تم إكمال طلبك!\n\n"
                msg += f"🆔 رقم الطلب: #{order_id}\n"
                msg += f"📦 المنتج: {order_data.get('item_name', '-')}\n"
                if order_data.get('hidden_data'):
                    msg += f"\n🔐 البيانات:\n{order_data.get('hidden_data')}"
                bot.send_message(int(buyer_id), msg)
            except Exception as e:
                logger.error(f"Error notifying buyer: {e}")
        
        return jsonify({'status': 'success', 'message': 'تم إكمال الطلب'})
        
    except Exception as e:
        logger.error(f"Error completing order: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== APIs كروت الشحن =====================

@admin_bp.route('/api/admin/get_charge_keys')
def api_get_charge_keys():
    """جلب جميع كروت الشحن"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        keys = []
        
        if db:
            keys_ref = db.collection('charge_keys').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
            
            for doc in keys_ref:
                key_data = doc.to_dict()
                key_data['id'] = doc.id
                
                if key_data.get('created_at'):
                    key_data['created_at'] = key_data['created_at'].isoformat() if hasattr(key_data['created_at'], 'isoformat') else str(key_data['created_at'])
                if key_data.get('used_at'):
                    key_data['used_at'] = key_data['used_at'].isoformat() if hasattr(key_data['used_at'], 'isoformat') else str(key_data['used_at'])
                
                keys.append(key_data)
        
        return jsonify({
            'status': 'success',
            'keys': keys
        })
        
    except Exception as e:
        logger.error(f"Error getting charge keys: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/delete_charge_key', methods=['POST'])
def api_delete_charge_key():
    """حذف كرت شحن"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        data = request.json
        key_id = data.get('key_id')
        
        if not key_id or not db:
            return jsonify({'status': 'error', 'message': 'بيانات ناقصة'})
        
        db.collection('charge_keys').document(key_id).delete()
        
        return jsonify({'status': 'success', 'message': 'تم الحذف'})
        
    except Exception as e:
        logger.error(f"Error deleting charge key: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== إدارة المشرفين =====================

@admin_bp.route('/admin/managers')
def admin_managers_page():
    """صفحة إدارة المشرفين"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    
    return render_template('admin_managers.html', active_page='managers', owner_id=ADMIN_ID)


@admin_bp.route('/api/admin/managers/list')
def api_list_managers():
    """جلب قائمة المشرفين"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        admins = []
        if db:
            admins_ref = db.collection('admins').stream()
            for doc in admins_ref:
                admin_data = doc.to_dict()
                admin_data['id'] = doc.id
                
                # تحويل التاريخ
                if admin_data.get('added_at'):
                    admin_data['added_at'] = admin_data['added_at'].isoformat() if hasattr(admin_data['added_at'], 'isoformat') else str(admin_data['added_at'])
                
                admins.append(admin_data)
        
        return jsonify({
            'status': 'success',
            'admins': admins
        })
        
    except Exception as e:
        logger.error(f"Error listing managers: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/managers/add', methods=['POST'])
def api_add_manager():
    """إضافة مشرف جديد"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        data = request.json
        telegram_id = data.get('telegram_id', '').strip()
        name = data.get('name', '').strip()
        note = data.get('note', '').strip()
        
        if not telegram_id:
            return jsonify({'status': 'error', 'message': 'أدخل Telegram ID'})
        
        if not telegram_id.isdigit():
            return jsonify({'status': 'error', 'message': 'ID يجب أن يكون أرقام فقط'})
        
        # التحقق من أن الـ ID ليس المالك
        if int(telegram_id) == ADMIN_ID:
            return jsonify({'status': 'error', 'message': 'لا يمكن إضافة المالك كمشرف'})
        
        # محاولة جلب اسم المشرف من تليجرام إذا لم يُدخل اسم
        fetched_name = name
        telegram_username = None
        if not name and BOT_ACTIVE and bot:
            try:
                chat_info = bot.get_chat(int(telegram_id))
                fetched_name = chat_info.first_name or ''
                if chat_info.last_name:
                    fetched_name += ' ' + chat_info.last_name
                telegram_username = chat_info.username
            except Exception as e:
                logger.warning(f"Could not fetch Telegram info for {telegram_id}: {e}")
                fetched_name = f'مشرف {telegram_id[-4:]}'
        
        if not fetched_name:
            fetched_name = f'مشرف {telegram_id[-4:]}'
        
        if db:
            # التحقق من عدم وجود المشرف مسبقاً
            existing = db.collection('admins').where(filter=FieldFilter('telegram_id', '==', telegram_id)).get()
            if list(existing):
                return jsonify({'status': 'error', 'message': 'هذا المشرف موجود مسبقاً'})
            
            # إضافة المشرف
            admin_data = {
                'telegram_id': telegram_id,
                'name': fetched_name,
                'note': note,
                'added_at': firestore.SERVER_TIMESTAMP,
                'added_by': str(ADMIN_ID)
            }
            if telegram_username:
                admin_data['username'] = telegram_username
            
            db.collection('admins').add(admin_data)
            
            # إشعار المالك
            notify_owner(
                f"✅ <b>تمت إضافة مشرف جديد</b>\n\n"
                f"👨‍💼 <b>الاسم:</b> {fetched_name}\n"
                f"🆔 <b>ID:</b> <code>{telegram_id}</code>\n"
                f"📱 <b>Username:</b> @{telegram_username or 'غير متوفر'}\n"
                f"📝 <b>ملاحظة:</b> {note or 'لا يوجد'}"
            )
            
            return jsonify({
                'status': 'success', 
                'message': f'تمت إضافة المشرف: {fetched_name}',
                'admin_name': fetched_name
            })
        
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})
        
    except Exception as e:
        logger.error(f"Error adding manager: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/managers/delete', methods=['POST'])
def api_delete_manager():
    """حذف مشرف"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        data = request.json
        admin_id = data.get('admin_id')
        
        if not admin_id or not db:
            return jsonify({'status': 'error', 'message': 'بيانات ناقصة'})
        
        # جلب بيانات المشرف قبل الحذف للإشعار
        admin_doc = db.collection('admins').document(admin_id).get()
        admin_info = admin_doc.to_dict() if admin_doc.exists else {}
        
        db.collection('admins').document(admin_id).delete()
        
        # إشعار المالك
        notify_owner(
            f"🗑️ <b>تم حذف مشرف</b>\n\n"
            f"👨‍💼 <b>الاسم:</b> {admin_info.get('name', 'غير محدد')}\n"
            f"🆔 <b>ID:</b> <code>{admin_info.get('telegram_id', '-')}</code>"
        )
        
        return jsonify({'status': 'success', 'message': 'تم الحذف'})
        
    except Exception as e:
        logger.error(f"Error deleting manager: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== إدارة طلبات السحب =====================

@admin_bp.route('/admin/withdrawals')
def admin_withdrawals_page():
    """صفحة طلبات السحب"""
    if not session.get('is_admin'):
        return redirect('/dashboard')
    return render_template('admin_withdrawals.html', active_page='withdrawals')


@admin_bp.route('/api/admin/get_withdrawals')
def api_get_withdrawals():
    """جلب جميع طلبات السحب"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        withdrawals = []
        if db:
            requests_ref = db.collection('withdrawal_requests').order_by('created_at', direction=firestore.Query.DESCENDING)
            for doc in requests_ref.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                
                # تحويل التاريخ
                if data.get('created_at'):
                    data['created_at'] = data['created_at'].isoformat() if hasattr(data['created_at'], 'isoformat') else str(data['created_at'])
                
                # فك تشفير البيانات الحساسة
                if data.get('iban_encrypted'):
                    try:
                        data['iban'] = decrypt_data(data['iban_encrypted'])
                    except:
                        data['iban'] = '***مشفر***'
                
                if data.get('wallet_number_encrypted'):
                    try:
                        data['wallet_number'] = decrypt_data(data['wallet_number_encrypted'])
                    except:
                        data['wallet_number'] = '***مشفر***'
                
                withdrawals.append(data)
        
        return jsonify({'status': 'success', 'withdrawals': withdrawals})
    
    except Exception as e:
        logger.error(f"Error getting withdrawals: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/withdrawal/<withdrawal_id>/approve', methods=['POST'])
def api_approve_withdrawal(withdrawal_id):
    """الموافقة على طلب السحب"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        if not db:
            return jsonify({'status': 'error', 'message': 'خطأ في الاتصال'})
        
        doc_ref = db.collection('withdrawal_requests').document(withdrawal_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({'status': 'error', 'message': 'الطلب غير موجود'})
        
        data = doc.to_dict()
        if data.get('status') != 'pending':
            return jsonify({'status': 'error', 'message': 'هذا الطلب تم معالجته مسبقاً'})
        
        # تحديث حالة الطلب
        doc_ref.update({
            'status': 'approved',
            'approved_at': firestore.SERVER_TIMESTAMP,
            'approved_by': session.get('admin_id', 'admin')
        })
        
        # إرسال إشعار للمستخدم
        user_id = data.get('user_id')
        amount = data.get('amount', 0)
        net_amount = data.get('net_amount', 0)
        
        if bot and user_id:
            try:
                message = f"""✅ تمت الموافقة على طلب السحب

💰 المبلغ المطلوب: {amount} ر.س
💵 المبلغ الصافي: {net_amount} ر.س

سيتم تحويل المبلغ خلال 1 إلى 5 ساعات وتكون بحسابك."""
                bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Error sending approval notification: {e}")
        
        # إنشاء فاتورة PDF وإرسالها بالبريد الإلكتروني
        try:
            user_email = None
            if user_id:
                user_ref = db.collection('users').document(str(user_id))
                user_doc = user_ref.get()
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    user_email = user_data.get('linked_email') or user_data.get('email')
            
            if user_email:
                invoice_data = {
                    'withdrawal_id': withdrawal_id,
                    'amount': amount,
                    'net_amount': net_amount,
                    'fee': data.get('fee', 0),
                    'fee_percentage': data.get('fee_percentage', 0),
                    'withdrawal_type': data.get('withdrawal_type', 'bank'),
                    'bank_name': data.get('bank_name', ''),
                    'iban': data.get('iban', ''),
                    'wallet_type': data.get('wallet_type', ''),
                    'wallet_number': data.get('wallet_number', ''),
                    'full_name': data.get('full_name', 'غير محدد'),
                    'created_at': data.get('created_at'),
                    'approved_at': data.get('approved_at'),
                }
                send_withdrawal_invoice_email(user_email, invoice_data)
                logger.info(f"📧 جاري إرسال فاتورة السحب إلى: {user_email}")
            else:
                logger.info(f"⚠️ لا يوجد بريد إلكتروني للمستخدم {user_id} - لم يتم إرسال فاتورة")
        except Exception as e:
            logger.error(f"Error sending withdrawal invoice: {e}")
        
        return jsonify({'status': 'success', 'message': 'تم الموافقة على الطلب'})
    
    except Exception as e:
        logger.error(f"Error approving withdrawal: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/withdrawal/<withdrawal_id>/reject', methods=['POST'])
def api_reject_withdrawal(withdrawal_id):
    """رفض طلب السحب وإرجاع الرصيد"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        if not db:
            return jsonify({'status': 'error', 'message': 'خطأ في الاتصال'})
        
        req_data = request.get_json() or {}
        reason = req_data.get('reason', '')
        
        doc_ref = db.collection('withdrawal_requests').document(withdrawal_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({'status': 'error', 'message': 'الطلب غير موجود'})
        
        data = doc.to_dict()
        if data.get('status') != 'pending':
            return jsonify({'status': 'error', 'message': 'هذا الطلب تم معالجته مسبقاً'})
        
        user_id = data.get('user_id')
        amount = data.get('amount', 0)
        
        # إرجاع الرصيد للمستخدم
        user_ref = db.collection('users').document(str(user_id))
        user_doc = user_ref.get()
        if user_doc.exists:
            current_balance = user_doc.to_dict().get('balance', 0)
            user_ref.update({'balance': current_balance + amount})
        
        # تحديث حالة الطلب
        doc_ref.update({
            'status': 'rejected',
            'rejected_at': firestore.SERVER_TIMESTAMP,
            'rejected_by': session.get('admin_id', 'admin'),
            'rejection_reason': reason
        })
        
        # إرسال إشعار للمستخدم
        if bot and user_id:
            try:
                message = f"""❌ تم رفض طلب السحب

💰 المبلغ: {amount} ر.س
📝 السبب: {reason if reason else 'لم يتم تحديد السبب'}

تم إرجاع المبلغ لرصيدك."""
                bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Error sending rejection notification: {e}")
        
        return jsonify({'status': 'success', 'message': 'تم رفض الطلب وإرجاع الرصيد'})
    
    except Exception as e:
        logger.error(f"Error rejecting withdrawal: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/withdrawal/<withdrawal_id>/resend', methods=['POST'])
def api_resend_withdrawal_notification(withdrawal_id):
    """إعادة إرسال إشعار طلب السحب للأدمن"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        if not db:
            return jsonify({'status': 'error', 'message': 'خطأ في الاتصال'})
        
        doc = db.collection('withdrawal_requests').document(withdrawal_id).get()
        
        if not doc.exists:
            return jsonify({'status': 'error', 'message': 'الطلب غير موجود'})
        
        data = doc.to_dict()
        
        # فك تشفير البيانات
        iban = ''
        wallet_number = ''
        if data.get('iban_encrypted'):
            try:
                iban = decrypt_data(data['iban_encrypted'])
            except:
                iban = '***خطأ في فك التشفير***'
        
        if data.get('wallet_number_encrypted'):
            try:
                wallet_number = decrypt_data(data['wallet_number_encrypted'])
            except:
                wallet_number = '***خطأ في فك التشفير***'
        
        # إرسال الإشعار للأدمن
        if bot and ADMIN_ID:
            status_text = {
                'pending': '⏳ قيد الانتظار',
                'approved': '✅ تمت الموافقة',
                'rejected': '❌ مرفوض'
            }.get(data.get('status', 'pending'), '❓ غير معروف')
            
            if data.get('withdrawal_type') == 'bank':
                bank_info = f"""🏦 تحويل بنكي
البنك: {data.get('bank_name', '-')}
IBAN: {iban}"""
            else:
                bank_info = f"""💳 محفظة إلكترونية
نوع المحفظة: {data.get('wallet_type', '-')}
رقم المحفظة: {wallet_number}"""
            
            message = f"""🔄 إعادة إرسال - طلب سحب رصيد

👤 المستخدم: {data.get('user_id', '-')}
📛 الاسم: {data.get('full_name', '-')}
💰 المبلغ: {data.get('amount', 0)} ر.س
💸 الرسوم ({data.get('fee_percentage', 0)}%): {data.get('fee', 0)} ر.س
✅ الصافي: {data.get('net_amount', 0)} ر.س

{bank_info}

📊 الحالة: {status_text}
📅 التاريخ: {data.get('created_at', '-')}"""
            
            try:
                bot.send_message(chat_id=ADMIN_ID, text=message)
                return jsonify({'status': 'success', 'message': 'تم إرسال الإشعار'})
            except Exception as e:
                logger.error(f"Error sending notification: {e}")
                return jsonify({'status': 'error', 'message': f'خطأ في الإرسال: {str(e)}'})
        else:
            return jsonify({'status': 'error', 'message': 'البوت غير متاح'})
    
    except Exception as e:
        logger.error(f"Error resending notification: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== إدارة أرقام الجوال =====================

@admin_bp.route('/api/admin/reset_phone', methods=['POST'])
def reset_customer_phone():
    """حذف أو تغيير رقم الجوال الموثق - للمالك فقط"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    # التحقق أن المستخدم هو المالك
    current_admin_id = session.get('admin_id')
    if str(current_admin_id) != str(ADMIN_ID):
        return jsonify({'status': 'error', 'message': 'هذا الإجراء متاح للمالك فقط'}), 403
    
    try:
        data = request.json or {}
        user_id = data.get('user_id')
        action = data.get('action', 'delete')  # delete أو change
        new_phone = data.get('new_phone', '')
        
        if not user_id:
            return jsonify({'status': 'error', 'message': 'معرف المستخدم مطلوب'})
        
        if not db:
            return jsonify({'status': 'error', 'message': 'قاعدة البيانات غير متاحة'})
        
        # البحث عن المستخدم
        user_ref = db.collection('users').document(str(user_id))
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'status': 'error', 'message': 'المستخدم غير موجود'})
        
        user_data = user_doc.to_dict()
        old_phone = user_data.get('verified_phone', '')
        
        if action == 'delete':
            # حذف رقم الجوال
            user_ref.update({
                'verified_phone': firestore.DELETE_FIELD,
                'phone_verified': False,
                'phone_reset_at': time.time(),
                'phone_reset_by': str(ADMIN_ID)
            })
            
            # إشعار المستخدم
            if bot:
                try:
                    bot.send_message(
                        int(user_id),
                        "⚠️ *تم إلغاء توثيق رقم جوالك*\n\n"
                        "تم حذف رقم الجوال الموثق من حسابك بواسطة الإدارة.\n"
                        "يمكنك إضافة رقم جديد من صفحة الإعدادات.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            return jsonify({
                'status': 'success',
                'message': f'تم حذف رقم الجوال {old_phone} بنجاح'
            })
        
        elif action == 'change':
            # تغيير رقم الجوال
            if not new_phone or len(new_phone) != 10 or not new_phone.startswith('05'):
                return jsonify({'status': 'error', 'message': 'رقم الجوال غير صالح (يجب أن يبدأ بـ 05 ويتكون من 10 أرقام)'})
            
            user_ref.update({
                'verified_phone': new_phone,
                'phone_verified': True,
                'phone_changed_at': time.time(),
                'phone_changed_by': str(ADMIN_ID)
            })
            
            # إشعار المستخدم
            if bot:
                try:
                    bot.send_message(
                        int(user_id),
                        f"📱 *تم تغيير رقم جوالك*\n\n"
                        f"الرقم القديم: `{old_phone}`\n"
                        f"الرقم الجديد: `{new_phone}`\n\n"
                        f"تم التغيير بواسطة الإدارة.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            return jsonify({
                'status': 'success',
                'message': f'تم تغيير الرقم من {old_phone} إلى {new_phone}'
            })
        
        else:
            return jsonify({'status': 'error', 'message': 'إجراء غير معروف'})
    
    except Exception as e:
        logger.error(f"Error resetting phone: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


# ===================== إدارة الكاش =====================

@admin_bp.route('/api/admin/clear_cache', methods=['POST'])
def api_clear_cache():
    """مسح الكاش لتحديث البيانات فوراً"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        from firebase_utils import clear_cache, get_cache_status
        
        # مسح كل الكاش
        clear_cache()
        
        return jsonify({
            'status': 'success',
            'message': '✅ تم مسح الكاش بنجاح! البيانات ستُجلب من Firebase مباشرة.'
        })
    
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return jsonify({'status': 'error', 'message': 'حدث خطأ'})


@admin_bp.route('/api/admin/cache_status')
def api_cache_status():
    """عرض حالة الكاش"""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'غير مصرح'}), 403
    
    try:
        from firebase_utils import get_cache_status
        status = get_cache_status()
        
        return jsonify({
            'status': 'success',
            'cache': status
        })
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ===================== دالة التهيئة =====================

def init_admin(app_db, app_bot, admin_id, app_limiter=None, bot_active=False):
    """تهيئة لوحة التحكم"""
    global db, bot, ADMIN_ID, limiter, BOT_ACTIVE
    db = app_db
    bot = app_bot
    ADMIN_ID = admin_id
    limiter = app_limiter
    BOT_ACTIVE = bot_active
    
    # تحميل إعدادات العرض من Firebase
    try:
        if db:
            doc = db.collection('settings').document('display').get()
            if doc.exists:
                data = doc.to_dict()
                display_settings['categories_columns'] = data.get('categories_columns', 3)
    except:
        pass
    
    print("✅ تم تهيئة لوحة التحكم")
