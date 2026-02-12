"""
Auth Routes - تسجيل الدخول والتحقق والتسجيل
"""
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template
from extensions import db, bot
from utils import regenerate_session, generate_code, validate_phone
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD

# === Authentica API (WhatsApp/SMS OTP) ===
try:
    from services.authentica_service import (
        is_authentica_configured,
        send_otp_whatsapp,
        verify_otp_authentica,
        format_phone_number
    )
    AUTHENTICA_AVAILABLE = is_authentica_configured()
    print(f"📱 Authentica Service: {'✅ متاح' if AUTHENTICA_AVAILABLE else '❌ غير مُعد (AUTHENTICA_API_KEY فارغ)'}")
except ImportError as e:
    print(f"⚠️ Authentica service not available: {e}")
    AUTHENTICA_AVAILABLE = False
    is_authentica_configured = lambda: False

logger = logging.getLogger(__name__)

# استيراد نظام كشف الدخول الجديد
try:
    from security_middleware import detect_new_login, log_login_success, log_login_failed, SecurityEvent, log_security_event
    NEW_LOGIN_DETECTION = True
    SECURITY_LOGGING = True
except ImportError:
    NEW_LOGIN_DETECTION = False
    SECURITY_LOGGING = False
    detect_new_login = lambda *args, **kwargs: {'is_new': False}
    log_login_success = lambda *args, **kwargs: None
    log_login_failed = lambda *args, **kwargs: None

auth_bp = Blueprint('auth', __name__)

# ==================== حماية من محاولات تسجيل الدخول ====================
# تخزين مؤقت لمحاولات الدخول الفاشلة
login_failed_attempts = {}  # {ip: {'count': 0, 'blocked_until': 0, 'last_attempt': 0}}

def check_login_rate_limit():
    """التحقق من rate limit لتسجيل الدخول"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    current_time = time.time()
    
    if client_ip in login_failed_attempts:
        attempt_data = login_failed_attempts[client_ip]
        
        # التحقق من الحظر
        if attempt_data.get('blocked_until', 0) > current_time:
            remaining = int(attempt_data['blocked_until'] - current_time)
            return False, f'⛔ تم حظرك مؤقتاً. حاول بعد {remaining} ثانية'
        
        # إعادة تعيين العداد بعد 15 دقيقة من آخر محاولة
        if current_time - attempt_data.get('last_attempt', 0) > 900:
            login_failed_attempts[client_ip] = {'count': 0, 'blocked_until': 0, 'last_attempt': current_time}
    
    return True, None

def record_failed_login():
    """تسجيل محاولة دخول فاشلة"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    current_time = time.time()
    
    if client_ip not in login_failed_attempts:
        login_failed_attempts[client_ip] = {'count': 0, 'blocked_until': 0, 'last_attempt': current_time}
    
    login_failed_attempts[client_ip]['count'] += 1
    login_failed_attempts[client_ip]['last_attempt'] = current_time
    
    attempts = login_failed_attempts[client_ip]['count']
    
    # حظر بعد 5 محاولات فاشلة لمدة 15 دقيقة
    if attempts >= 5:
        login_failed_attempts[client_ip]['blocked_until'] = current_time + 900  # 15 دقيقة
        logger.warning(f"⚠️ حظر IP {client_ip} بسبب محاولات دخول فاشلة متكررة")
        return 0
    
    return 5 - attempts

def reset_login_attempts():
    """إعادة تعيين عداد المحاولات بعد دخول ناجح"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    if client_ip in login_failed_attempts:
        del login_failed_attempts[client_ip]


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """صفحة تسجيل الدخول"""
    if request.method == 'POST':
        # 🔒 التحقق من Rate Limit
        allowed, error_msg = check_login_rate_limit()
        if not allowed:
            return jsonify({'success': False, 'message': error_msg})
        
        data = request.json
        user_id = data.get('user_id', '').strip()
        code = data.get('code', '').strip()
        
        if not user_id or not code:
            return jsonify({'success': False, 'message': 'الرجاء إدخال المعرّف والكود'})
        
        try:
            user_id = int(user_id)
        except:
            record_failed_login()
            return jsonify({'success': False, 'message': 'معرف غير صحيح'})
        
        # التحقق من الكود
        user_doc = db.collection('users').document(str(user_id)).get()
        if not user_doc.exists:
            record_failed_login()
            return jsonify({'success': False, 'message': 'المستخدم غير موجود'})
        
        user_data = user_doc.to_dict()
        stored_code = user_data.get('verification_code', '')
        code_time = user_data.get('code_time', 0)
        
        # التحقق من صلاحية الكود (ساعة واحدة)
        if time.time() - code_time > 3600:
            record_failed_login()
            log_login_failed(user_id, reason='انتهت صلاحية الكود')
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'})
        
        if stored_code != code:
            remaining = record_failed_login()
            log_login_failed(user_id, reason='كود خاطئ')
            if remaining == 0:
                return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'})
            return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})
        
        # ✅ دخول ناجح - إعادة تعيين عداد المحاولات
        reset_login_attempts()
        
        # 🔒 تسجيل الدخول الناجح في سجل الأمان
        log_login_success(user_id)
        
        # تسجيل الدخول
        session.clear()
        session['user_id'] = user_id
        session['user_name'] = user_data.get('username', f'مستخدم {user_id}')
        session['profile_photo'] = user_data.get('profile_photo', '')
        session['login_time'] = time.time()
        regenerate_session()
        
        # كشف تسجيل الدخول من جهاز جديد
        if NEW_LOGIN_DETECTION:
            try:
                login_info = detect_new_login(db, user_id, bot)
                if login_info.get('is_new'):
                    session['new_device_login'] = True
                    # 🔒 تسجيل الدخول من جهاز جديد
                    if SECURITY_LOGGING:
                        log_security_event(SecurityEvent.LOGIN_NEW_DEVICE, user_id)
            except Exception as e:
                pass  # لا نوقف تسجيل الدخول إذا فشل الكشف
        
        return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})
    
    # GET - عرض صفحة تسجيل الدخول
    if session.get('user_id'):
        return redirect('/')
    return render_template('login_user.html')

@auth_bp.route('/verify-code', methods=['POST'])
def verify_code_api():
    """التحقق من الكود"""
    # 🔒 التحقق من Rate Limit
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})
    
    data = request.json
    user_id = data.get('user_id', '').strip()
    code = data.get('code', '').strip()
    
    if not user_id or not code:
        return jsonify({'success': False, 'message': 'بيانات غير كاملة'})
    
    try:
        user_id = int(user_id)
    except:
        record_failed_login()
        return jsonify({'success': False, 'message': 'معرف غير صحيح'})
    
    user_doc = db.collection('users').document(str(user_id)).get()
    if not user_doc.exists:
        record_failed_login()
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'})
    
    user_data = user_doc.to_dict()
    stored_code = user_data.get('verification_code', '')
    code_time = user_data.get('code_time', 0)
    
    # التحقق من الصلاحية
    if time.time() - code_time > 3600:
        record_failed_login()
        return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'})
    
    if stored_code != code:
        remaining = record_failed_login()
        if remaining == 0:
            return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'})
        return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})
    
    # ✅ نجاح
    reset_login_attempts()
    return jsonify({'success': True, 'message': 'تم التحقق'})

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """تسجيل الخروج"""
    session.clear()
    return jsonify({'success': True, 'message': 'تم تسجيل الخروج'})

@auth_bp.route('/register', methods=['POST'])
def register():
    """تسجيل مستخدم جديد"""
    data = request.json
    user_id = data.get('user_id')
    username = data.get('username', '').strip()
    phone = data.get('phone', '').strip()
    
    if not user_id or not username:
        return jsonify({'success': False, 'message': 'بيانات غير كاملة'})
    
    # التحقق من رقم الهاتف
    if phone and not validate_phone(phone):
        return jsonify({'success': False, 'message': 'رقم هاتف غير صحيح'})
    
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'message': 'معرف غير صحيح'})
    
    # فحص وجود المستخدم
    user_doc = db.collection('users').document(str(user_id)).get()
    if user_doc.exists:
        return jsonify({'success': False, 'message': 'المستخدم موجود بالفعل'})
    
    # إنشاء مستخدم جديد
    new_user = {
        'user_id': user_id,
        'username': username,
        'phone': phone,
        'balance': 0.0,
        'created_at': time.time(),
        'verification_code': generate_code(),
        'code_time': time.time()
    }
    
    db.collection('users').document(str(user_id)).set(new_user)
    
    return jsonify({
        'success': True,
        'message': 'تم التسجيل بنجاح',
        'code': new_user['verification_code']
    })

@auth_bp.route('/user-profile', methods=['GET'])
def get_user_profile():
    """جلب بيانات المستخدم"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'غير مسجل دخول'})
    
    user_doc = db.collection('users').document(str(user_id)).get()
    if not user_doc.exists:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'})
    
    user_data = user_doc.to_dict()
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': user_data.get('username'),
            'phone': user_data.get('phone'),
            'balance': user_data.get('balance', 0),
            'profile_photo': user_data.get('profile_photo', '')
        }
    })


# ==================== نظام تسجيل الدخول بالإيميل ====================

def send_email_otp(to_email, code):
    """إرسال كود التحقق عبر الإيميل"""
    try:
        if not SMTP_EMAIL or not SMTP_PASSWORD:
            print("❌ إعدادات SMTP غير مكتملة")
            return False
            
        msg = MIMEMultipart('alternative')
        msg['From'] = f"TR Store <{SMTP_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = "🔐 كود الدخول - TR Store"

        # تصميم الرسالة HTML
        html_body = f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head><meta charset="UTF-8"></head>
        <body style="margin: 0; padding: 0; background-color: #f0f2f5; font-family: 'Segoe UI', Tahoma, sans-serif;">
            <div style="max-width: 500px; margin: 30px auto; background: white; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); overflow: hidden;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🔐 TR Store</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">رمز التحقق الخاص بك</p>
                </div>
                <div style="padding: 40px 30px; text-align: center;">
                    <p style="color: #666; font-size: 16px; margin-bottom: 30px;">مرحباً! 👋<br>استخدم الرمز التالي لتسجيل الدخول:</p>
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px; border-radius: 15px; display: inline-block;">
                        <span style="font-size: 36px; font-weight: bold; color: white; letter-spacing: 8px;">{code}</span>
                    </div>
                    <p style="color: #999; font-size: 14px; margin-top: 30px;">⏰ هذا الرمز صالح لمدة <strong>10 دقائق</strong> فقط</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                    <p style="color: #aaa; font-size: 12px;">⚠️ إذا لم تطلب هذا الرمز، تجاهل هذا الإيميل</p>
                </div>
                <div style="background: #f8f9fa; padding: 20px; text-align: center;">
                    <p style="color: #888; font-size: 12px; margin: 0;">TR Store © 2026</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(f"رمز التحقق: {code}", 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        print(f"📧 محاولة إرسال إيميل إلى: {to_email} عبر {SMTP_SERVER}:{SMTP_PORT}")
        
        # محاولة SSL أولاً (port 465)
        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
                print(f"✅ تم إرسال الإيميل بنجاح إلى: {to_email}")
                return True
        except Exception as ssl_error:
            print(f"⚠️ فشل SSL: {ssl_error}, جاري تجربة TLS...")
            
        # محاولة TLS كخيار ثاني (port 587)
        try:
            with smtplib.SMTP(SMTP_SERVER, 587, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
                print(f"✅ تم إرسال الإيميل بنجاح (TLS) إلى: {to_email}")
                return True
        except Exception as tls_error:
            print(f"❌ فشل TLS أيضاً: {tls_error}")
            return False
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ خطأ في المصادقة: {e}")
        return False
    except Exception as e:
        print(f"❌ خطأ في إرسال الإيميل: {e}")
        return False


@auth_bp.route('/api/auth/send-code', methods=['POST'])
def send_code_email():
    """إرسال كود التحقق للإيميل"""
    # 🔒 التحقق من Rate Limit
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})
    
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})
        
    email = data.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        return jsonify({'success': False, 'message': 'الرجاء إدخال بريد إلكتروني صحيح'})

    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        results = list(query.stream())

        if results:
            user_doc = results[0]
            user_id = user_doc.id
            user_ref = users_ref.document(user_id)
            print(f"✅ تم العثور على المستخدم: {user_id}")
        else:
            # الحساب غير مسجل - إعلام المستخدم
            return jsonify({'success': False, 'not_registered': True, 'message': 'الحساب غير مسجل. يمكنك إنشاء حساب جديد'})

        # توليد وحفظ الكود
        new_code = generate_code()
        user_ref.update({
            'verification_code': new_code,
            'code_time': time.time()
        })
        
        # إرسال الإيميل
        if send_email_otp(email, new_code):
            return jsonify({'success': True, 'message': f'✅ تم إرسال الرمز إلى {email}', 'email': email})
        else:
            # إذا فشل الإيميل، نحاول إرسال عبر Telegram
            try:
                message_text = f"📧 كود التحقق للدخول:\n\n<code>{new_code}</code>\n\n⏰ صالح لمدة 10 دقائق"
                bot.send_message(int(user_id), message_text, parse_mode='HTML')
                return jsonify({'success': True, 'message': '✅ تم إرسال الرمز عبر Telegram', 'email': email})
            except:
                return jsonify({'success': False, 'message': 'فشل الإرسال!'})

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في النظام'})


# ==================== تسجيل حساب جديد بالإيميل ====================

# تخزين مؤقت لبيانات التسجيل
_pending_registrations = {}  # {phone: {'code': '...', 'name': '...', 'time': ...}}

@auth_bp.route('/api/auth/register-send-code', methods=['POST'])
def register_send_code():
    """إرسال كود التحقق عبر واتساب لتسجيل حساب جديد"""
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})

    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})

    phone = data.get('phone', '').strip()
    name = data.get('name', '').strip()

    if not phone:
        return jsonify({'success': False, 'message': 'الرجاء إدخال رقم الجوال'})
    if not name:
        return jsonify({'success': False, 'message': 'الرجاء إدخال الاسم'})

    # تنظيف رقم الجوال
    import re
    phone = phone.replace(' ', '').replace('-', '').replace('+', '')
    if phone.startswith('966'):
        phone = '0' + phone[3:]
    elif phone.startswith('5') and len(phone) == 9:
        phone = '0' + phone

    try:
        # تأكد الرقم غير مسجل
        query = db.collection('users').where('phone', '==', phone).limit(1)
        results = list(query.stream())
        if results:
            return jsonify({'success': False, 'message': 'هذا الرقم مسجل بالفعل. يمكنك تسجيل الدخول مباشرة'})

        # إرسال الكود عبر واتساب (Authentica)
        otp_sent = False
        try:
            from services.authentica_service import send_otp_whatsapp, is_authentica_configured
            if is_authentica_configured():
                result = send_otp_whatsapp(phone)
                if result.get('success'):
                    _pending_registrations[phone] = {
                        'via_authentica': True,
                        'name': name,
                        'time': time.time()
                    }
                    otp_sent = True
        except Exception as e:
            print(f"⚠️ Authentica register error: {e}")

        if not otp_sent:
            # Fallback: توليد كود وإرساله عبر تلغرام
            new_code = generate_code()
            _pending_registrations[phone] = {
                'code': new_code,
                'name': name,
                'time': time.time()
            }
            # محاولة إرسال عبر تلغرام إذا كان ممكن
            print(f"⚠️ Registration fallback - code: {new_code} for phone: {phone}")

        return jsonify({'success': True, 'message': f'✅ تم إرسال كود التحقق على واتساب'})

    except Exception as e:
        print(f"❌ Register send code error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في النظام'})


@auth_bp.route('/api/auth/register-verify', methods=['POST'])
def register_verify():
    """التحقق من الكود وإنشاء حساب جديد"""
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})

    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})

    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()

    # تنظيف رقم الجوال
    phone = phone.replace(' ', '').replace('-', '').replace('+', '')
    if phone.startswith('966'):
        phone = '0' + phone[3:]
    elif phone.startswith('5') and len(phone) == 9:
        phone = '0' + phone

    if not phone or not code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال الرقم والكود'})

    pending = _pending_registrations.get(phone)
    if not pending:
        return jsonify({'success': False, 'message': 'لم يتم طلب كود لهذا الرقم. أعد المحاولة'})

    # التحقق من انتهاء الصلاحية (10 دقائق)
    if time.time() - pending['time'] > 600:
        _pending_registrations.pop(phone, None)
        return jsonify({'success': False, 'message': 'انتهت صلاحية الكود. اطلب كود جديد'})

    # التحقق من الكود
    code_valid = False
    if pending.get('via_authentica'):
        # تحقق عبر Authentica
        try:
            from services.authentica_service import verify_otp_authentica
            result = verify_otp_authentica(phone, code)
            code_valid = result.get('success', False)
        except Exception as e:
            print(f"⚠️ Authentica verify error: {e}")
    elif pending.get('code'):
        # تحقق محلي (fallback)
        code_valid = str(pending['code']) == code

    if not code_valid:
        remaining = record_failed_login()
        if remaining == 0:
            return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'})
        return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})

    try:
        # ✅ إنشاء الحساب
        reset_login_attempts()
        import uuid
        new_user_id = str(uuid.uuid4())[:12]

        new_user = {
            'phone': phone,
            'username': pending['name'],
            'first_name': pending['name'],
            'balance': 0.0,
            'created_at': time.time(),
            'registered_via': 'whatsapp',
            'phone_verified': True,
            'phone_verified_at': time.time()
        }

        db.collection('users').document(new_user_id).set(new_user)
        _pending_registrations.pop(phone, None)

        # تسجيل الدخول تلقائياً
        regenerate_session()
        session['user_id'] = new_user_id
        session['user_name'] = pending['name']
        session['logged_in'] = True
        session['login_time'] = time.time()
        session.permanent = True
        session.modified = True

        log_login_success(new_user_id)
        print(f"✅ تم تسجيل حساب جديد: {new_user_id} - {phone}")

        return jsonify({'success': True, 'message': '🎉 تم إنشاء حسابك بنجاح! جاري نقلك...', 'is_new': True})

    except Exception as e:
        print(f"❌ Register verify error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء إنشاء الحساب'})


@auth_bp.route('/api/auth/login', methods=['POST'])
def login_email():
    """التحقق من الكود وتسجيل الدخول بالإيميل"""
    # 🔒 التحقق من Rate Limit
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})
    
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})
        
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    
    if not email or not code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال البريد والكود'})
    
    try:
        query = db.collection('users').where('email', '==', email).limit(1)
        results = list(query.stream())
        
        if not results:
            record_failed_login()
            return jsonify({'success': False, 'message': 'الحساب غير موجود'})
            
        user_doc = results[0]
        user_data = user_doc.to_dict()
        
        # التحقق من انتهاء صلاحية الكود (10 دقائق)
        code_time = user_data.get('code_time', 0)
        if time.time() - code_time > 600:
            record_failed_login()
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود، اطلب كود جديد'})
        
        # التحقق من الكود
        saved_code = str(user_data.get('verification_code', ''))
        if saved_code == code:
            # ✅ نجاح - إعادة تعيين عداد المحاولات
            reset_login_attempts()
            
            # تجديد الجلسة للأمان
            regenerate_session()
            
            # دخول ناجح
            session['user_id'] = user_doc.id
            session['user_name'] = user_data.get('username', user_data.get('first_name', 'مستخدم'))
            session['user_email'] = email
            session['logged_in'] = True
            session['login_time'] = time.time()  # ⚠️ مهم جداً!
            session.permanent = True
            session.modified = True
            
            # مسح الكود بعد الاستخدام
            db.collection('users').document(user_doc.id).update({
                'verification_code': None,
                'code_time': None
            })
            
            # 🔒 تسجيل الدخول الناجح
            log_login_success(user_doc.id)
            
            print(f"✅ تم تسجيل دخول المستخدم بالإيميل: {user_doc.id}")
            return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})
        else:
            remaining = record_failed_login()
            log_login_failed(user_doc.id, reason='كود خاطئ')
            if remaining == 0:
                return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'})
            return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})
            
    except Exception as e:
        print(f"❌ Login Error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء الدخول'})


# ==================== تسجيل الدخول بالجوال (WhatsApp/SMS) ====================

@auth_bp.route('/api/auth/send-code-phone', methods=['POST'])
def send_code_phone():
    """إرسال كود التحقق للجوال عبر WhatsApp"""
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})

    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})

    phone = str(data.get('phone', '')).strip()
    if not phone:
        return jsonify({'success': False, 'message': 'الرجاء إدخال رقم الجوال'})

    if not validate_phone(phone):
        return jsonify({'success': False, 'message': 'رقم الجوال غير صحيح'})

    try:
        # البحث عن المستخدم برقم الجوال (بصيغ مختلفة)
        users_ref = db.collection('users')
        user_doc = None
        user_id = None

        # تجربة صيغ مختلفة
        import re
        clean = phone.replace(' ', '').replace('-', '').replace('+', '')
        search_phones = [phone]
        if clean.startswith('05') and len(clean) == 10:
            search_phones.append('+966' + clean[1:])
            search_phones.append('966' + clean[1:])
        elif clean.startswith('966'):
            search_phones.append('0' + clean[3:])
            search_phones.append('+' + clean)

        for sp in search_phones:
            query = users_ref.where('phone', '==', sp).limit(1)
            results = list(query.stream())
            if results:
                user_doc = results[0]
                user_id = user_doc.id
                break

        if not user_doc:
            return jsonify({'success': False, 'message': 'لا يوجد حساب مرتبط بهذا الرقم'})

        # توليد كود
        new_code = generate_code()
        users_ref.document(user_id).update({
            'verification_code': new_code,
            'code_time': time.time()
        })

        # التحقق من توفر Authentica
        if not AUTHENTICA_AVAILABLE or not is_authentica_configured():
            # Fallback: إرسال عبر Telegram
            try:
                message_text = f"📱 كود التحقق للدخول:\n\n<code>{new_code}</code>\n\n⏰ صالح لمدة 10 دقائق"
                bot.send_message(int(user_id), message_text, parse_mode='HTML')
                return jsonify({
                    'success': True,
                    'message': '✅ تم إرسال الكود عبر Telegram',
                    'user_id': user_id,
                    'method': 'telegram'
                })
            except:
                return jsonify({'success': False, 'message': 'خدمة الرسائل غير متاحة'})

        # إرسال عبر WhatsApp
        result = send_otp_whatsapp(phone, otp_code=new_code)

        if result['success']:
            return jsonify({
                'success': True,
                'message': result['message'],
                'user_id': user_id,
                'method': 'whatsapp'
            })
        else:
            # Fallback: إرسال عبر Telegram
            try:
                message_text = f"📱 كود التحقق للدخول:\n\n<code>{new_code}</code>\n\n⏰ صالح لمدة 10 دقائق"
                bot.send_message(int(user_id), message_text, parse_mode='HTML')
                return jsonify({
                    'success': True,
                    'message': '✅ تم إرسال الكود عبر Telegram (واتساب غير متاح)',
                    'user_id': user_id,
                    'method': 'telegram'
                })
            except:
                return jsonify({'success': False, 'message': result['message']})

    except Exception as e:
        print(f"❌ Phone Send Code Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'حدث خطأ في النظام'})


@auth_bp.route('/api/auth/login-phone', methods=['POST'])
def login_phone():
    """التحقق من الكود وتسجيل الدخول بالجوال"""
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})

    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})

    phone = str(data.get('phone', '')).strip()
    code = str(data.get('code', '')).strip()
    user_id = str(data.get('user_id', '')).strip()

    if not code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال الكود'})

    try:
        # البحث عن المستخدم
        if user_id:
            user_ref = db.collection('users').document(user_id)
            user_doc = user_ref.get()
            if not user_doc.exists:
                record_failed_login()
                return jsonify({'success': False, 'message': 'الحساب غير موجود'})
        elif phone:
            import re
            clean = phone.replace(' ', '').replace('-', '').replace('+', '')
            search_phones = [phone]
            if clean.startswith('05'):
                search_phones.append('+966' + clean[1:])
                search_phones.append('966' + clean[1:])
            elif clean.startswith('966'):
                search_phones.append('0' + clean[3:])

            user_doc = None
            for sp in search_phones:
                query = db.collection('users').where('phone', '==', sp).limit(1)
                results = list(query.stream())
                if results:
                    user_doc = results[0]
                    user_id = user_doc.id
                    break

            if not user_doc:
                record_failed_login()
                return jsonify({'success': False, 'message': 'الحساب غير موجود'})
        else:
            return jsonify({'success': False, 'message': 'بيانات غير كاملة'})

        user_data = user_doc.to_dict()

        # التحقق من الصلاحية (10 دقائق)
        code_time = user_data.get('code_time', 0)
        if time.time() - code_time > 600:
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود، اطلب كود جديد'})

        # التحقق عبر Authentica API أولاً
        if AUTHENTICA_AVAILABLE and phone:
            verify_result = verify_otp_authentica(phone, code)
            if not verify_result.get('success'):
                # Fallback للتحقق المحلي
                saved_code = str(user_data.get('verification_code', ''))
                if saved_code != code:
                    remaining = record_failed_login()
                    if remaining == 0:
                        return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة'})
                    return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})
        else:
            # التحقق المحلي فقط
            saved_code = str(user_data.get('verification_code', ''))
            if saved_code != code:
                remaining = record_failed_login()
                if remaining == 0:
                    return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة'})
                return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})

        # ✅ تسجيل دخول ناجح
        reset_login_attempts()
        regenerate_session()

        session['user_id'] = user_id if isinstance(user_id, str) else user_doc.id
        session['user_name'] = user_data.get('username', user_data.get('first_name', 'مستخدم'))
        session['user_phone'] = phone
        session['logged_in'] = True
        session['login_time'] = time.time()
        session.permanent = True
        session.modified = True

        # مسح الكود + توثيق الرقم تلقائياً
        update_data = {
            'verification_code': None,
            'code_time': None,
            'phone_verified': True,
            'phone_verified_at': time.time()
        }
        # تحديث رقم الجوال إذا لم يكن محفوظاً
        if phone and not user_data.get('phone'):
            update_data['phone'] = phone
        db.collection('users').document(str(session['user_id'])).update(update_data)

        log_login_success(session['user_id'])
        print(f"✅ تم تسجيل دخول المستخدم بالجوال: {session['user_id']}")
        return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})

    except Exception as e:
        print(f"❌ Phone Login Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء الدخول'})
