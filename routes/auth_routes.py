"""
Auth Routes - تسجيل الدخول والتحقق والتسجيل
"""
from flask import Blueprint, request, jsonify, session, redirect, url_for
from extensions import db, bot
from utils import regenerate_session, generate_code, validate_phone
import time
import logging

logger = logging.getLogger(__name__)

# استيراد نظام كشف الدخول الجديد
try:
    from security_middleware import detect_new_login
    NEW_LOGIN_DETECTION = True
except ImportError:
    NEW_LOGIN_DETECTION = False
    detect_new_login = lambda *args, **kwargs: {'is_new': False}

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
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'})
        
        if stored_code != code:
            remaining = record_failed_login()
            if remaining == 0:
                return jsonify({'success': False, 'message': '⛔ تم حظرك لمدة 15 دقيقة بسبب محاولات فاشلة متكررة'})
            return jsonify({'success': False, 'message': f'الكود غير صحيح. المحاولات المتبقية: {remaining}'})
        
        # ✅ دخول ناجح - إعادة تعيين عداد المحاولات
        reset_login_attempts()
        
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
            except Exception as e:
                pass  # لا نوقف تسجيل الدخول إذا فشل الكشف
        
        return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})
    
    return {'page': 'login'}

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
