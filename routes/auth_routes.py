"""
Auth Routes - تسجيل الدخول والتحقق والتسجيل
"""
from flask import Blueprint, request, jsonify, session, redirect, url_for
from firebase_utils import (
    get_user, add_user, get_balance, add_balance,
    db
)
from utils import regenerate_session, generate_code, validate_phone
import time

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """صفحة تسجيل الدخول"""
    if request.method == 'POST':
        data = request.json
        user_id = data.get('user_id', '').strip()
        code = data.get('code', '').strip()
        
        if not user_id or not code:
            return jsonify({'success': False, 'message': 'الرجاء إدخال المعرّف والكود'})
        
        try:
            user_id = int(user_id)
        except:
            return jsonify({'success': False, 'message': 'معرف غير صحيح'})
        
        # التحقق من الكود
        user_doc = db.collection('users').document(str(user_id)).get()
        if not user_doc.exists:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود'})
        
        user_data = user_doc.to_dict()
        stored_code = user_data.get('verification_code', '')
        code_time = user_data.get('code_time', 0)
        
        # التحقق من صلاحية الكود (ساعة واحدة)
        if time.time() - code_time > 3600:
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'})
        
        if stored_code != code:
            return jsonify({'success': False, 'message': 'الكود غير صحيح'})
        
        # تسجيل الدخول
        session.clear()
        session['user_id'] = user_id
        session['user_name'] = user_data.get('username', f'مستخدم {user_id}')
        session['profile_photo'] = user_data.get('profile_photo', '')
        regenerate_session()
        
        return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})
    
    return {'page': 'login'}

@auth_bp.route('/verify-code', methods=['POST'])
def verify_code_api():
    """التحقق من الكود"""
    data = request.json
    user_id = data.get('user_id', '').strip()
    code = data.get('code', '').strip()
    
    if not user_id or not code:
        return jsonify({'success': False, 'message': 'بيانات غير كاملة'})
    
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'message': 'معرف غير صحيح'})
    
    user_doc = db.collection('users').document(str(user_id)).get()
    if not user_doc.exists:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود'})
    
    user_data = user_doc.to_dict()
    stored_code = user_data.get('verification_code', '')
    code_time = user_data.get('code_time', 0)
    
    # التحقق من الصلاحية
    if time.time() - code_time > 3600:
        return jsonify({'success': False, 'message': 'انتهت صلاحية الكود'})
    
    if stored_code != code:
        return jsonify({'success': False, 'message': 'الكود غير صحيح'})
    
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
