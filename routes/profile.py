"""
Profile Routes - مسارات صفحة الحساب الشخصي
"""
from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from extensions import db, logger, bot
import json
import random
import time
import base64
import io
from datetime import datetime

# محاولة استيراد مكتبة TOTP
try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    print("⚠️ pyotp أو qrcode غير متوفرة - 2FA لن تعمل")

profile_bp = Blueprint('profile', __name__)

# تخزين مؤقت لأكواد التحقق من الإيميل
email_verification_codes = {}  # {user_id: {'code': '123456', 'email': 'x@y.com', 'created_at': timestamp}}

# تخزين مؤقت لإعداد 2FA
pending_2fa_setup = {}  # {user_id: {'secret': 'XXXX', 'created_at': timestamp}}

@profile_bp.route('/profile')
def profile():
    """صفحة الحساب الشخصي"""
    try:
        # التحقق من تسجيل الدخول
        if 'user_id' not in session or not session['user_id']:
            return redirect(url_for('auth.login_page'))
        
        user_id = session['user_id']
        
        # جلب بيانات المستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return redirect(url_for('auth.login_page'))
        
        user_data = user_doc.to_dict()
        
        # جلب آخر 3 طلبات من collection('orders')
        orders = []
        try:
            # جلب جميع الطلبات مرتبة حسب التاريخ (بدون where للتجنب من الحاجة للـ index)
            # ثم تصفيتها في الكود
            orders_query = db.collection('orders').order_by(
                'created_at', direction='DESCENDING'
            ).limit(100)  # جلب 100 لأننا سنصفيها
            
            orders_docs = orders_query.stream()
            
            for order_doc in orders_docs:
                order_data = order_doc.to_dict()
                # تصفية حسب buyer_id
                if order_data.get('buyer_id') == user_id:
                    orders.append({
                        'id': order_doc.id,
                        'product_name': order_data.get('item_name', 'منتج'),
                        'price': order_data.get('price', 0),
                        'status': order_data.get('status', 'pending'),
                        'created_at': order_data.get('created_at'),
                        'quantity': 1,
                        'total': order_data.get('price', 0),
                        'payment_method': order_data.get('payment_method', 'wallet')
                    })
                    # توقف بعد جلب 3 طلبات
                    if len(orders) >= 3:
                        break
        except Exception as e:
            logger.error(f"خطأ في جلب الطلبات: {e}")
            orders = []
        
        # تحويل التواريخ إلى صيغة محلية
        for order in orders:
            if order.get('created_at'):
                try:
                    # تحويل Timestamp إلى datetime
                    timestamp = order['created_at']
                    if hasattr(timestamp, 'strftime'):
                        order['date_formatted'] = timestamp.strftime('%d/%m/%Y %H:%M')
                    else:
                        order['date_formatted'] = str(timestamp)
                except:
                    order['date_formatted'] = str(order.get('created_at', ''))
        
        # حالة الطلب بصيغة عربية
        status_map = {
            'pending': '⏳ قيد الانتظار',
            'completed': '✅ مكتمل',
            'failed': '❌ فشل',
            'refunded': '🔄 مسترجع',
            'processing': '⚙️ قيد المعالجة',
            'delivered': '📦 تم التسليم'
        }
        
        for order in orders:
            order['status_ar'] = status_map.get(order.get('status'), 'غير معروف')
        
        # التحقق من وجود الصورة
        profile_photo = user_data.get('profile_photo', '')
        
        return render_template('profile.html',
            user_name=user_data.get('name', 'المستخدم'),
            user_id=user_id,
            profile_photo=profile_photo,
            balance=user_data.get('balance', 0),
            orders=orders,
            # بيانات الأمان
            email=user_data.get('email', ''),
            email_verified=user_data.get('email_verified', False),
            totp_enabled=user_data.get('totp_enabled', False)
        )
    
    except Exception as e:
        logger.error(f"خطأ في صفحة الحساب: {e}")
        return redirect(url_for('auth.login_page'))


@profile_bp.route('/api/profile')
def api_profile():
    """API لجلب بيانات الحساب"""
    try:
        if 'user_id' not in session or not session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        
        user_id = session['user_id']
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        
        user_data = user_doc.to_dict()
        
        return jsonify({
            'user_id': user_id,
            'name': user_data.get('name', ''),
            'profile_photo': user_data.get('profile_photo', ''),
            'balance': user_data.get('balance', 0)
        })
    
    except Exception as e:
        logger.error(f"خطأ في API الحساب: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== توثيق الإيميل ====================

@profile_bp.route('/api/send_email_code', methods=['POST'])
def send_email_code():
    """إرسال كود التحقق للبريد الإلكتروني"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        # التحقق من صحة الإيميل
        import re
        if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            return jsonify({'success': False, 'message': 'بريد إلكتروني غير صحيح'}), 400
        
        # توليد كود عشوائي
        code = str(random.randint(100000, 999999))
        
        # حفظ الكود مؤقتاً
        email_verification_codes[user_id] = {
            'code': code,
            'email': email,
            'created_at': time.time()
        }
        
        # إرسال الكود عبر Telegram Bot
        try:
            message = f"""
📧 كود توثيق البريد الإلكتروني:

<code>{code}</code>

📩 البريد: {email}
⏰ صالح لمدة 10 دقائق

⚠️ لا تشارك هذا الكود مع أحد!
"""
            bot.send_message(int(user_id), message, parse_mode='HTML')
            
            return jsonify({
                'success': True,
                'message': 'تم إرسال كود التحقق عبر Telegram'
            })
        except Exception as e:
            logger.error(f"خطأ في إرسال كود الإيميل: {e}")
            return jsonify({'success': False, 'message': 'فشل إرسال الكود'}), 500
    
    except Exception as e:
        logger.error(f"خطأ في send_email_code: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ'}), 500


@profile_bp.route('/api/verify_email_code', methods=['POST'])
def verify_email_code():
    """التحقق من كود الإيميل"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        data = request.get_json()
        code = data.get('code', '').strip()
        
        # التحقق من وجود كود معلق
        if user_id not in email_verification_codes:
            return jsonify({'success': False, 'message': 'لم يتم طلب كود التحقق'}), 400
        
        stored = email_verification_codes[user_id]
        
        # التحقق من انتهاء الصلاحية (10 دقائق)
        if time.time() - stored['created_at'] > 600:
            del email_verification_codes[user_id]
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'}), 400
        
        # التحقق من صحة الكود
        if code != stored['code']:
            return jsonify({'success': False, 'message': 'الكود غير صحيح'}), 400
        
        # حفظ الإيميل في قاعدة البيانات
        email = stored['email']
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'email': email,
            'email_verified': True,
            'email_verified_at': time.time()
        })
        
        # حذف الكود المؤقت
        del email_verification_codes[user_id]
        
        return jsonify({
            'success': True,
            'message': 'تم توثيق البريد الإلكتروني بنجاح'
        })
    
    except Exception as e:
        logger.error(f"خطأ في verify_email_code: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ'}), 500


# ==================== المصادقة الثنائية 2FA ====================

@profile_bp.route('/api/setup_2fa', methods=['POST'])
def setup_2fa():
    """إعداد المصادقة الثنائية - إنشاء مفتاح سري و QR"""
    try:
        if not TOTP_AVAILABLE:
            return jsonify({'success': False, 'message': 'خدمة 2FA غير متوفرة حالياً'}), 503
        
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        user_name = session.get('user_name', 'User')
        
        # التحقق من أن 2FA غير مفعل مسبقاً
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data.get('totp_enabled'):
                return jsonify({'success': False, 'message': '2FA مفعل مسبقاً'}), 400
        
        # إنشاء مفتاح سري جديد
        secret = pyotp.random_base32()
        
        # إنشاء رابط للتطبيق
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=f"User_{user_id}",
            issuer_name="TR Store"
        )
        
        # إنشاء صورة QR
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # تحويل الصورة إلى base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # حفظ المفتاح مؤقتاً (لم يتم التفعيل بعد)
        pending_2fa_setup[user_id] = {
            'secret': secret,
            'created_at': time.time()
        }
        
        return jsonify({
            'success': True,
            'qr_code': f'data:image/png;base64,{qr_base64}',
            'secret': secret
        })
    
    except Exception as e:
        logger.error(f"خطأ في setup_2fa: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ'}), 500


@profile_bp.route('/api/verify_2fa_setup', methods=['POST'])
def verify_2fa_setup():
    """التحقق من الكود وتفعيل 2FA"""
    try:
        if not TOTP_AVAILABLE:
            return jsonify({'success': False, 'message': 'خدمة 2FA غير متوفرة'}), 503
        
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        data = request.get_json()
        code = data.get('code', '').strip()
        
        # التحقق من وجود إعداد معلق
        if user_id not in pending_2fa_setup:
            return jsonify({'success': False, 'message': 'لم يتم بدء إعداد 2FA'}), 400
        
        setup = pending_2fa_setup[user_id]
        
        # التحقق من انتهاء الصلاحية (10 دقائق)
        if time.time() - setup['created_at'] > 600:
            del pending_2fa_setup[user_id]
            return jsonify({'success': False, 'message': 'انتهت صلاحية الإعداد'}), 400
        
        # التحقق من صحة الكود
        secret = setup['secret']
        totp = pyotp.TOTP(secret)
        
        if not totp.verify(code):
            return jsonify({'success': False, 'message': 'الكود غير صحيح'}), 400
        
        # حفظ 2FA في قاعدة البيانات
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'totp_enabled': True,
            'totp_secret': secret,
            'totp_enabled_at': time.time()
        })
        
        # حذف الإعداد المؤقت
        del pending_2fa_setup[user_id]
        
        # إرسال إشعار عبر Telegram
        try:
            bot.send_message(int(user_id), """
🔐 تم تفعيل المصادقة الثنائية بنجاح!

✅ حسابك الآن محمي بطبقة أمان إضافية.
📱 ستحتاج تطبيق Google Authenticator عند تسجيل الدخول.

⚠️ احتفظ بالمفتاح السري في مكان آمن للطوارئ!
""")
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': 'تم تفعيل المصادقة الثنائية بنجاح'
        })
    
    except Exception as e:
        logger.error(f"خطأ في verify_2fa_setup: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ'}), 500


@profile_bp.route('/api/disable_2fa', methods=['POST'])
def disable_2fa():
    """تعطيل المصادقة الثنائية"""
    try:
        if not TOTP_AVAILABLE:
            return jsonify({'success': False, 'message': 'خدمة 2FA غير متوفرة'}), 503
        
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        data = request.get_json()
        code = data.get('code', '').strip()
        
        # جلب المفتاح السري من قاعدة البيانات
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 404
        
        user_data = user_doc.to_dict()
        
        if not user_data.get('totp_enabled'):
            return jsonify({'success': False, 'message': '2FA غير مفعل'}), 400
        
        secret = user_data.get('totp_secret')
        if not secret:
            return jsonify({'success': False, 'message': 'مفتاح غير موجود'}), 400
        
        # التحقق من صحة الكود
        totp = pyotp.TOTP(secret)
        if not totp.verify(code):
            return jsonify({'success': False, 'message': 'الكود غير صحيح'}), 400
        
        # تعطيل 2FA
        user_ref.update({
            'totp_enabled': False,
            'totp_secret': None,
            'totp_disabled_at': time.time()
        })
        
        # إرسال إشعار
        try:
            bot.send_message(int(user_id), """
⚠️ تم تعطيل المصادقة الثنائية!

❌ حسابك لم يعد محمياً بـ 2FA.
🔐 ننصحك بإعادة تفعيلها لحماية أفضل.
""")
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': 'تم تعطيل المصادقة الثنائية'
        })
    
    except Exception as e:
        logger.error(f"خطأ في disable_2fa: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ'}), 500