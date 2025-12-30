"""
Web Routes - صفحات الويب
"""
from flask import Blueprint, render_template, session
from firebase_utils import (
    get_balance, get_user_cart, get_categories, 
    get_products_by_category, get_product_by_id
)
import json

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def index():
    """الصفحة الرئيسية - عرض الفئات الافتراضية 3×3"""
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'ضيف')
    profile_photo = session.get('profile_photo', '')
    is_logged_in = bool(user_id)
    
    # 1. جلب الرصيد
    balance = 0.0
    if user_id:
        try:
            balance = get_balance(user_id)
        except:
            balance = 0.0
    
    # 2. جلب الفئات
    categories = get_categories()
    for cat in categories:
        products = get_products_by_category(cat.get('name', ''))
        cat['products_count'] = len(products)
    
    # 3. جلب عدد منتجات السلة
    cart_count = 0
    if user_id:
        cart = get_user_cart(str(user_id)) or {}
        cart_count = len(cart.get('items', []))
    
    # 4. تحضير JSON للفئات
    categories_json = json.dumps([{'id': cat.get('id', ''), 'name': cat.get('name', '')} for cat in categories])
    
    return render_template('categories.html',
                         categories=categories,
                         categories_json=categories_json,
                         balance=balance,
                         current_user_id=user_id or 0,
                         current_user=user_id,
                         user_name=user_name,
                         profile_photo=profile_photo,
                         is_logged_in=is_logged_in,
                         cart_count=cart_count)

@web_bp.route('/t/<category_id>')
def category_products(category_id):
    """صفحة منتجات الفئة"""
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'ضيف')
    profile_photo = session.get('profile_photo', '')
    is_logged_in = bool(user_id)
    
    # جلب الرصيد
    balance = 0.0
    if user_id:
        balance = get_balance(user_id)
    
    # جلب عدد السلة
    cart_count = 0
    if user_id:
        cart = get_user_cart(str(user_id)) or {}
        cart_count = len(cart.get('items', []))
    
    return render_template('category.html',
                         category_id=category_id,
                         balance=balance,
                         current_user_id=user_id or 0,
                         current_user=user_id,
                         user_name=user_name,
                         profile_photo=profile_photo,
                         is_logged_in=is_logged_in,
                         cart_count=cart_count)

@web_bp.route('/404')
def page_not_found():
    """صفحة الخطأ 404"""
    return render_template('404.html'), 404

@web_bp.errorhandler(404)
def handle_404(e):
    """معالج خطأ 404"""
    return render_template('404.html'), 404
