"""
Profile Routes - مسارات صفحة الحساب الشخصي
"""
from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from extensions import db, logger, bot, ADMIN_ID
from google.cloud import firestore
from telebot import types
import json
import random
import time
import base64
import io
import os
from datetime import datetime

# استيراد أدوات التشفير
try:
    from encryption_utils import encrypt_data, decrypt_data
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    encrypt_data = lambda x: x
    decrypt_data = lambda x: x
    print("⚠️ encryption_utils غير متوفرة - التشفير معطل")

# محاولة استيراد مكتبة TOTP
try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    print("⚠️ pyotp أو qrcode غير متوفرة - 2FA لن تعمل")

# استيراد نظام الإشعارات
try:
    from notifications import notify_withdrawal_request, notify_owner
except ImportError:
    notify_withdrawal_request = lambda *args, **kwargs: None
    notify_owner = lambda *args, **kwargs: None

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
            return redirect(url_for('auth.login'))
        
        user_id = session['user_id']
        
        # جلب بيانات المستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return redirect(url_for('auth.login'))
        
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
        
        # حساب المبلغ المتاح للسحب العادي باستخدام المعادلة الذهبية
        normal_withdraw_amount = 0
        instant_withdraw_amount = user_data.get('balance', 0)
        current_balance = user_data.get('balance', 0)
        
        try:
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # ===== المعادلة الذهبية: المتاح = الرصيد الحالي - المجمد =====
            # فترة التجميد (10 دقائق للاختبار، 72*60 للإنتاج)
            FREEZE_MINUTES = 10  # غيّرها إلى 72*60 للإنتاج
            
            total_frozen_balance = 0.0
            min_minutes_left = 0
            recent_charges = []  # آخر 3 شحنات للعرض
            
            # جلب شحنات المستخدم
            try:
                all_user_charges = db.collection('charge_history')\
                    .where('user_id', '==', user_id)\
                    .get()
            except Exception as query_error:
                print(f"⚠️ Query failed: {query_error}")
                all_user_charges = []
            
            for charge_doc in all_user_charges:
                charge = charge_doc.to_dict()
                charge_amt = float(charge.get('amount', 0))
                charge_ts = charge.get('timestamp')
                
                # --- تصحيح التعامل مع التوقيت ---
                charge_dt = None
                
                if charge_ts:
                    # التعامل مع أنواع التوقيت المختلفة من Firebase
                    if hasattr(charge_ts, 'timestamp'):
                        # DatetimeWithNanoseconds من Firebase
                        charge_dt = datetime.datetime.fromtimestamp(charge_ts.timestamp(), datetime.timezone.utc)
                    elif isinstance(charge_ts, datetime.datetime):
                        # datetime عادي - نتأكد أنه UTC
                        charge_dt = charge_ts.replace(tzinfo=datetime.timezone.utc) if charge_ts.tzinfo is None else charge_ts
                    elif isinstance(charge_ts, (int, float)):
                        # Unix timestamp (رقم)
                        charge_dt = datetime.datetime.fromtimestamp(charge_ts, datetime.timezone.utc)
                
                # إذا لم يوجد وقت صالح، نعتبره "الآن" (مجمد)
                if not charge_dt:
                    charge_dt = now
                
                # حساب الفرق بالدقائق
                time_diff = now - charge_dt
                minutes_passed = time_diff.total_seconds() / 60
                
                # طباعة للمراقبة (يظهر في Terminal)
                print(f"💰 Charge: {charge_amt} SAR, Mins Passed: {minutes_passed:.2f}")
                
                # شرط التجميد
                if minutes_passed < FREEZE_MINUTES:
                    total_frozen_balance += charge_amt
                    minutes_left = FREEZE_MINUTES - minutes_passed
                    if minutes_left > min_minutes_left:
                        min_minutes_left = int(minutes_left)
            
            # جلب آخر 3 شحنات للعرض (بدون order_by لتجنب مشكلة الـ Index)
            try:
                all_recent_charges = db.collection('charge_history')\
                    .where('user_id', '==', user_id)\
                    .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                    .limit(3)\
                    .get()
            except:
                # fallback بدون order_by
                all_recent_charges = db.collection('charge_history')\
                    .where('user_id', '==', user_id)\
                    .limit(3)\
                    .get()
            
            for charge_doc in all_recent_charges:
                charge = charge_doc.to_dict()
                charge_amount = float(charge.get('amount', 0))
                charge_ts = charge.get('timestamp')
                
                is_available = True
                minutes_left_display = 0
                
                if charge_ts:
                    try:
                        if hasattr(charge_ts, 'timestamp'):
                            charge_dt = datetime.datetime.fromtimestamp(charge_ts.timestamp(), datetime.timezone.utc)
                        elif hasattr(charge_ts, 'replace'):
                            if charge_ts.tzinfo is None:
                                charge_dt = charge_ts.replace(tzinfo=datetime.timezone.utc)
                            else:
                                charge_dt = charge_ts
                        elif isinstance(charge_ts, (int, float)):
                            charge_dt = datetime.datetime.fromtimestamp(charge_ts, datetime.timezone.utc)
                        else:
                            charge_dt = now  # افتراضي
                        
                        minutes_passed = (now - charge_dt).total_seconds() / 60
                        is_available = minutes_passed >= 10  # 10 دقائق للاختبار
                        if not is_available:
                            minutes_left_display = max(0, int(10 - minutes_passed))
                    except:
                        is_available = True
                
                method_names = {
                    'key': 'كود شحن',
                    'charge': 'كود شحن',
                    'edfapay': 'بطاقة/فاتورة',
                    'payment': 'بطاقة/فاتورة',
                    'admin': 'من الإدارة',
                    'admin_charge': 'من الإدارة'
                }
                recent_charges.append({
                    'amount': charge_amount,
                    'method': method_names.get(charge.get('method', ''), charge.get('type', 'شحن')),
                    'is_available': is_available,
                    'minutes_left': minutes_left_display,
                    'date': charge.get('date', '')
                })
            
            # المعادلة النهائية: المتاح = الرصيد الحالي - المجمد
            normal_withdraw_amount = current_balance - total_frozen_balance
            
            # حماية: لا يمكن أن يكون المتاح بالسالب
            if normal_withdraw_amount < 0:
                normal_withdraw_amount = 0
            
            minutes_until_next = int(min_minutes_left) if min_minutes_left > 0 else 0
            frozen_balance = total_frozen_balance
            
        except Exception as e:
            logger.error(f"خطأ في حساب مبلغ السحب: {e}")
            # في حالة الخطأ، نعتبر كل الرصيد متاح (للتوافق مع الأرصدة القديمة)
            normal_withdraw_amount = current_balance
            recent_charges = []
            minutes_until_next = 0
            frozen_balance = 0
        
        # تقريب المبالغ
        normal_withdraw_amount = round(normal_withdraw_amount, 2)
        can_withdraw_normal = normal_withdraw_amount > 0
        
        return render_template('profile.html',
            user_name=user_data.get('name', 'المستخدم'),
            user_id=user_id,
            profile_photo=profile_photo,
            balance=user_data.get('balance', 0),
            orders=orders,
            # بيانات الأمان
            email=user_data.get('email', ''),
            email_verified=user_data.get('email_verified', False),
            totp_enabled=user_data.get('totp_enabled', False),
            # بيانات السحب
            can_withdraw_normal=can_withdraw_normal,
            normal_withdraw_amount=normal_withdraw_amount,
            instant_withdraw_amount=instant_withdraw_amount,
            frozen_balance=frozen_balance,
            min_minutes_left=minutes_until_next,
            minutes_until_withdraw=minutes_until_next,
            recent_charges=recent_charges
        )
    
    except Exception as e:
        logger.error(f"خطأ في صفحة الحساب: {e}")
        return redirect(url_for('auth.login'))


@profile_bp.route('/withdraw')
def withdraw_page():
    """صفحة سحب الرصيد مع سجل العمليات"""
    try:
        # التحقق من تسجيل الدخول
        if 'user_id' not in session or not session['user_id']:
            return redirect(url_for('auth.login'))
        
        user_id = session['user_id']
        
        # جلب بيانات المستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return redirect(url_for('auth.login'))
        
        user_data = user_doc.to_dict()
        balance = user_data.get('balance', 0)
        
        # === حساب الرصيد المتاح للسحب العادي ===
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        FREEZE_MINUTES = 10  # غيّرها إلى 72*60 للإنتاج
        
        total_frozen = 0.0
        min_minutes_left = 0
        
        try:
            user_charges = db.collection('charge_history').where('user_id', '==', user_id).get()
            
            for charge_doc in user_charges:
                charge = charge_doc.to_dict()
                charge_amount = float(charge.get('amount', 0))
                charge_ts = charge.get('timestamp')
                
                if charge_ts:
                    try:
                        if hasattr(charge_ts, 'timestamp'):
                            charge_dt = dt.datetime.fromtimestamp(charge_ts.timestamp(), dt.timezone.utc)
                        elif isinstance(charge_ts, (int, float)):
                            charge_dt = dt.datetime.fromtimestamp(charge_ts, dt.timezone.utc)
                        else:
                            charge_dt = now
                        
                        minutes_passed = (now - charge_dt).total_seconds() / 60
                        
                        if minutes_passed < FREEZE_MINUTES:
                            total_frozen += charge_amount
                            remaining = FREEZE_MINUTES - minutes_passed
                            if remaining > min_minutes_left:
                                min_minutes_left = int(remaining)
                    except:
                        pass
        except Exception as e:
            logger.error(f"خطأ في حساب الرصيد المجمد: {e}")
        
        available_for_normal = max(0, balance - total_frozen)
        
        # تحويل الدقائق لنص مقروء
        if min_minutes_left > 60:
            hours = min_minutes_left // 60
            mins = min_minutes_left % 60
            freeze_time_left = f"{hours} ساعة و {mins} دقيقة"
        else:
            freeze_time_left = f"{min_minutes_left} دقيقة"
        
        # === جلب الإحصائيات ===
        total_charges = 0
        purchases_count = 0
        withdrawals_count = 0
        
        # إجمالي الشحن
        try:
            charges = db.collection('charge_history').where('user_id', '==', user_id).get()
            for c in charges:
                total_charges += float(c.to_dict().get('amount', 0))
        except:
            pass
        
        # عدد المشتريات
        try:
            orders = db.collection('orders').where('buyer_id', '==', user_id).get()
            purchases_count = len(list(orders))
        except:
            pass
        
        # عدد السحوبات
        try:
            withdrawals = db.collection('withdrawal_requests').where('user_id', '==', user_id).get()
            withdrawals_count = len(list(withdrawals))
        except:
            pass
        
        # === جلب سجل العمليات ===
        activities = []
        
        # 1. الشحنات
        try:
            charges_ref = db.collection('charge_history').where('user_id', '==', user_id).get()
            for doc in charges_ref:
                data = doc.to_dict()
                
                # تحويل التاريخ
                date_str = data.get('date', '')
                if not date_str and data.get('timestamp'):
                    ts = data['timestamp']
                    try:
                        if hasattr(ts, 'timestamp'):
                            date_str = dt.datetime.fromtimestamp(ts.timestamp()).strftime('%Y-%m-%d %H:%M')
                        elif isinstance(ts, (int, float)):
                            date_str = dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                    except:
                        date_str = 'غير محدد'
                
                activities.append({
                    'type': 'charge',
                    'title': f"شحن رصيد ({data.get('method', 'كود')})",
                    'amount': data.get('amount', 0),
                    'date': date_str,
                    'timestamp': data.get('timestamp', 0),
                    'status': None
                })
        except Exception as e:
            logger.error(f"خطأ في جلب الشحنات: {e}")
        
        # 2. المشتريات
        try:
            orders_ref = db.collection('orders').where('buyer_id', '==', user_id).get()
            for doc in orders_ref:
                data = doc.to_dict()
                
                date_str = 'غير محدد'
                timestamp_val = 0
                if data.get('created_at'):
                    try:
                        created = data['created_at']
                        if hasattr(created, 'timestamp'):
                            timestamp_val = created.timestamp()
                            date_str = dt.datetime.fromtimestamp(created.timestamp()).strftime('%Y-%m-%d %H:%M')
                    except:
                        pass
                
                activities.append({
                    'type': 'purchase',
                    'title': f"شراء: {data.get('item_name', 'منتج')}",
                    'amount': data.get('price', 0),
                    'date': date_str,
                    'timestamp': timestamp_val,
                    'status': None
                })
        except Exception as e:
            logger.error(f"خطأ في جلب المشتريات: {e}")
        
        # 3. السحوبات
        try:
            withdraw_ref = db.collection('withdrawal_requests').where('user_id', '==', user_id).get()
            for doc in withdraw_ref:
                data = doc.to_dict()
                
                date_str = 'غير محدد'
                timestamp_val = 0
                if data.get('created_at'):
                    try:
                        created = data['created_at']
                        if hasattr(created, 'timestamp'):
                            timestamp_val = created.timestamp()
                            date_str = dt.datetime.fromtimestamp(created.timestamp()).strftime('%Y-%m-%d %H:%M')
                    except:
                        pass
                
                status = data.get('status', 'pending')
                status_map = {'pending': 'pending', 'approved': 'completed', 'rejected': 'rejected'}
                
                activities.append({
                    'type': 'withdraw',
                    'title': f"سحب ({data.get('withdraw_type', 'عادي')})",
                    'amount': data.get('amount', 0),
                    'date': date_str,
                    'timestamp': timestamp_val,
                    'status': status_map.get(status, status)
                })
        except Exception as e:
            logger.error(f"خطأ في جلب السحوبات: {e}")
        
        # ترتيب من الأحدث
        def get_ts(x):
            ts = x.get('timestamp', 0)
            if hasattr(ts, 'timestamp'):
                return ts.timestamp()
            elif hasattr(ts, 'seconds'):
                return ts.seconds
            elif isinstance(ts, (int, float)):
                return ts
            return 0
        
        activities.sort(key=get_ts, reverse=True)
        activities = activities[:50]  # آخر 50 عملية
        
        return render_template('withdraw.html',
            balance=balance,
            available_for_normal=round(available_for_normal, 2),
            frozen_amount=round(total_frozen, 2),
            freeze_time_left=freeze_time_left,
            total_charges=round(total_charges, 2),
            purchases_count=purchases_count,
            withdrawals_count=withdrawals_count,
            activities=activities
        )
    
    except Exception as e:
        logger.error(f"خطأ في صفحة السحب: {e}")
        return redirect('/')


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
        
        # حفظ 2FA في قاعدة البيانات (مع تشفير المفتاح)
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'totp_enabled': True,
            'totp_secret': encrypt_data(secret),
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
        
        # فك تشفير المفتاح
        secret = decrypt_data(secret)
        
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


# ==================== طلبات السحب ====================

@profile_bp.route('/api/withdraw', methods=['POST'])
def submit_withdraw():
    """إرسال طلب سحب"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
        
        user_id = session['user_id']
        data = request.get_json()
        
        # دعم كلا الاسمين: type و withdraw_type
        withdraw_type = data.get('withdraw_type') or data.get('type', '')  # normal أو instant
        method = data.get('method', '')  # wallet أو bank
        amount = data.get('amount', 0)
        full_name = data.get('full_name', '').strip()
        
        # التحقق من البيانات
        if withdraw_type not in ['normal', 'instant']:
            return jsonify({'success': False, 'message': 'نوع السحب غير صحيح'}), 400
        
        if method not in ['wallet', 'bank']:
            return jsonify({'success': False, 'message': 'طريقة السحب غير صحيحة'}), 400
        
        try:
            amount = float(amount)
            if amount <= 0:
                return jsonify({'success': False, 'message': 'المبلغ يجب أن يكون أكبر من صفر'}), 400
        except:
            return jsonify({'success': False, 'message': 'المبلغ غير صحيح'}), 400
        
        # التحقق من الاسم (جزئين على الأقل - فلان بن فلان)
        name_parts = full_name.split()
        if len(name_parts) < 2:
            return jsonify({'success': False, 'message': 'يجب إدخال الاسم الثنائي على الأقل (مثال: محمد بن أحمد)'}), 400
        
        # الحصول على بيانات المستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 404
        
        user_data = user_doc.to_dict()
        balance = user_data.get('balance', 0)
        
        # التحقق من الرصيد
        if amount > balance:
            return jsonify({'success': False, 'message': 'الرصيد غير كافٍ'}), 400
        
        # حساب الرسوم
        if withdraw_type == 'normal':
            fee_percent = 6.5
            
            # ===== المعادلة الذهبية: المتاح = الرصيد الحالي - المجمد =====
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # فترة التجميد (10 دقائق للاختبار، 72*60 للإنتاج)
            FREEZE_MINUTES = 10
            
            total_frozen_balance = 0.0
            min_minutes_left = 0
            
            try:
                # جلب شحنات المستخدم
                all_user_charges = db.collection('charge_history')\
                    .where('user_id', '==', user_id)\
                    .get()
                
                for charge_doc in all_user_charges:
                    charge = charge_doc.to_dict()
                    charge_amt = float(charge.get('amount', 0))
                    charge_ts = charge.get('timestamp')
                    
                    # --- تصحيح التعامل مع التوقيت ---
                    charge_dt = None
                    
                    if charge_ts:
                        if hasattr(charge_ts, 'timestamp'):
                            charge_dt = datetime.datetime.fromtimestamp(charge_ts.timestamp(), datetime.timezone.utc)
                        elif isinstance(charge_ts, datetime.datetime):
                            charge_dt = charge_ts.replace(tzinfo=datetime.timezone.utc) if charge_ts.tzinfo is None else charge_ts
                        elif isinstance(charge_ts, (int, float)):
                            charge_dt = datetime.datetime.fromtimestamp(charge_ts, datetime.timezone.utc)
                    
                    if not charge_dt:
                        charge_dt = now
                    
                    # حساب الفرق بالدقائق
                    time_diff = now - charge_dt
                    minutes_passed = time_diff.total_seconds() / 60
                    
                    # شرط التجميد
                    if minutes_passed < FREEZE_MINUTES:
                        total_frozen_balance += charge_amt
                        minutes_left = FREEZE_MINUTES - minutes_passed
                        if minutes_left > min_minutes_left:
                            min_minutes_left = int(minutes_left)
            except Exception as e:
                # في حالة الخطأ، نعتبر كل الرصيد متاح
                total_frozen_balance = 0
            
            # المعادلة النهائية: المتاح = الرصيد الحالي - المجمد
            current_available_balance = balance - total_frozen_balance
            
            # حماية: لا يمكن أن يكون المتاح بالسالب
            if current_available_balance < 0:
                current_available_balance = 0
            
            # التحقق: هل المبلغ المطلوب سحبه متاح؟
            if amount > current_available_balance:
                # تحويل الوقت المتبقي لصيغة مقروءة
                time_left_str = f'{int(min_minutes_left)} دقيقة'
                
                return jsonify({
                    'success': False, 
                    'message': f'رصيدك المتاح للسحب العادي هو {current_available_balance:.2f} ريال فقط. المبلغ المتبقي ({total_frozen_balance:.2f}) سيكون متاحاً بعد {time_left_str}.',
                    'available_for_normal': current_available_balance
                }), 400
        else:
            fee_percent = 8.0
        
        fee_amount = amount * (fee_percent / 100)
        net_amount = amount - fee_amount
        
        # بناء بيانات السحب
        withdraw_data = {
            'user_id': user_id,
            'user_name': user_data.get('name', 'غير معروف'),
            'amount': amount,
            'fee_percent': fee_percent,
            'fee_amount': fee_amount,
            'net_amount': net_amount,
            'withdraw_type': withdraw_type,
            'method': method,
            'full_name': full_name,
            'status': 'pending',  # pending, approved, rejected
            'created_at': firestore.SERVER_TIMESTAMP
        }
        
        # إضافة بيانات الطريقة
        if method == 'wallet':
            wallet_type = data.get('wallet_type', '').strip()
            wallet_number = data.get('wallet_number', '').strip()
            
            if not wallet_type or not wallet_number:
                return jsonify({'success': False, 'message': 'يجب إدخال نوع المحفظة ورقمها'}), 400
            
            withdraw_data['wallet_type'] = wallet_type
            # تشفير رقم المحفظة قبل الحفظ
            withdraw_data['wallet_number'] = encrypt_data(wallet_number) if ENCRYPTION_AVAILABLE else wallet_number
            method_display = f"محفظة {wallet_type}"
        else:
            bank_name = data.get('bank_name', '').strip()
            iban = data.get('iban', '').strip().upper()
            
            if not bank_name or not iban:
                return jsonify({'success': False, 'message': 'يجب إدخال اسم البنك ورقم الآيبان'}), 400
            
            # التحقق من صيغة IBAN
            if not iban.startswith('SA') or len(iban) != 24:
                return jsonify({'success': False, 'message': 'رقم الآيبان غير صحيح. يجب أن يبدأ بـ SA ويكون 24 حرف'}), 400
            
            withdraw_data['bank_name'] = bank_name
            # تشفير الآيبان قبل الحفظ
            withdraw_data['iban'] = encrypt_data(iban) if ENCRYPTION_AVAILABLE else iban
            method_display = f"حوالة بنكية - {bank_name}"
        
        # حفظ طلب السحب
        withdraw_ref = db.collection('withdrawal_requests').add(withdraw_data)
        
        # خصم المبلغ من الرصيد
        user_ref.update({
            'balance': firestore.Increment(-amount)
        })
        
        # إرسال إشعار للمستخدم
        try:
            type_text = "عادي (6.5%)" if withdraw_type == 'normal' else "فوري (8%)"
            user_message = f"""
💸 تم استلام طلب السحب!

📌 نوع السحب: {type_text}
💰 المبلغ: {amount:.2f} ريال
💵 الرسوم: {fee_amount:.2f} ريال
✅ المبلغ الصافي: {net_amount:.2f} ريال

📍 طريقة التحويل: {method_display}
👤 الاسم: {full_name}

⏰ وقت التحويل: 12-24 ساعة
📞 للاستفسار راسلنا
"""
            bot.send_message(int(user_id), user_message, parse_mode='HTML')
        except Exception as e:
            logger.error(f"خطأ في إرسال إشعار السحب للمستخدم: {e}")
        
        # إرسال إشعار للأدمن
        try:
            if not ADMIN_ID:
                logger.warning("لم يتم تعيين ADMIN_ID")
            else:
                if method == 'wallet':
                    # فك تشفير رقم المحفظة للعرض
                    display_wallet = decrypt_data(withdraw_data['wallet_number']) if ENCRYPTION_AVAILABLE else withdraw_data['wallet_number']
                    details = f"محفظة {withdraw_data['wallet_type']}: {display_wallet}"
                else:
                    # فك تشفير الآيبان للعرض
                    display_iban = decrypt_data(withdraw_data['iban']) if ENCRYPTION_AVAILABLE else withdraw_data['iban']
                    details = f"بنك {withdraw_data['bank_name']}\nIBAN: {display_iban}"
                
                admin_message = f"""
🔔 طلب سحب جديد!

👤 المستخدم: {user_data.get('name', 'غير معروف')}
🆔 الآيدي: {user_id}
📌 النوع: {type_text}

💰 المبلغ: {amount:.2f} ريال
💵 الرسوم: {fee_amount:.2f} ريال
✅ الصافي: {net_amount:.2f} ريال

📍 التحويل إلى:
👤 {full_name}
{details}
"""
                # الحصول على ID الطلب من withdraw_ref (tuple)
                request_id = withdraw_ref[1].id
                
                # إنشاء أزرار inline
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_approve = types.InlineKeyboardButton(
                    "✅ تم التحويل", 
                    callback_data=f"withdraw_approve_{request_id}_{user_id}"
                )
                btn_reject = types.InlineKeyboardButton(
                    "❌ رفض", 
                    callback_data=f"withdraw_reject_{request_id}_{user_id}"
                )
                markup.add(btn_approve, btn_reject)
                
                bot.send_message(ADMIN_ID, admin_message, parse_mode='HTML', reply_markup=markup)
                logger.info(f"✅ تم إرسال إشعار السحب للأدمن {ADMIN_ID}")
        except Exception as e:
            logger.error(f"خطأ في إرسال إشعار للأدمن: {e}")
        
        return jsonify({
            'success': True,
            'message': 'تم إرسال طلب السحب بنجاح! سيتم التحويل خلال 12-24 ساعة.',
            'net_amount': net_amount
        })
    
    except Exception as e:
        logger.error(f"خطأ في submit_withdraw: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في إرسال الطلب'}), 500