"""
API Routes - جميع endpoints الـ API
"""
from flask import Blueprint, request, jsonify, session
from firebase_utils import (
    get_collection_list, get_collection_data,
    get_balance, get_user_cart, get_products_by_category,
    get_categories
)
from security_utils import (
    require_session_user, validate_collection_name,
    sanitize_error_message, require_session_user
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

# ====== API Endpoints ======

@api_bp.route('/balance', methods=['GET'])
def get_user_balance():
    """جلب رصيد المستخدم الحالي"""
    user_id = session.get('user_id')
    
    if not user_id:
        return {'balance': 0}
    
    balance = get_balance(user_id)
    return {'balance': balance}

@api_bp.route('/tabs/list', methods=['GET'])
def get_tabs_list():
    """جلب قائمة Collections المتاحة كـ tabs - v2"""
    try:
        collections = get_collection_list()
        # تصفية Collections غير المطلوبة
        exclude = ['users', 'charge_keys', 'pending_payments', 'transactions', 'invoices']
        filtered = [c for c in collections if c not in exclude]
        
        return jsonify({
            'status': 'success',
            'tabs': filtered
        })
    except Exception as e:
        print(f"❌ خطأ في جلب قائمة التبويبات: {e}")
        return jsonify({'status': 'error', 'tabs': []})

@api_bp.route('/tabs/data/<collection_name>', methods=['GET'])
@require_session_user()
def get_tab_data(collection_name):
    """جلب البيانات من tab معين (collection) - محمي من Injection"""
    try:
        # ✅ استخدام Whitelist بدلاً من Blacklist
        try:
            validated_collection = validate_collection_name(collection_name)
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e), 'data': []}), 403
        
        limit = request.args.get('limit', 50, type=int)
        if limit > 100:
            limit = 100  # حد أقصى
        
        data = get_collection_data(validated_collection, limit=limit)
        
        return jsonify({
            'status': 'success',
            'collection': validated_collection,
            'count': len(data),
            'data': data
        })
    except Exception as e:
        error_msg = sanitize_error_message(str(e))
        print(f"❌ خطأ في جلب بيانات التبويب: {e}")
        return jsonify({'status': 'error', 'message': error_msg, 'data': []}), 500

@api_bp.route('/categories', methods=['GET'])
def get_categories_api():
    """جلب قائمة الفئات للـ JavaScript"""
    try:
        categories = get_categories()
        
        # إضافة عدد المنتجات لكل فئة
        for cat in categories:
            products = get_products_by_category(cat.get('name', ''))
            cat['products_count'] = len(products)
        
        return jsonify({
            'status': 'success',
            'categories': categories
        })
    except Exception as e:
        print(f"❌ خطأ في جلب الفئات: {e}")
        return jsonify({'status': 'error', 'categories': []})
