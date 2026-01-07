"""
Web Routes - صفحات الويب
"""
from flask import Blueprint, render_template, session
from firebase_utils import (
    get_balance, get_user_cart, get_categories, 
    get_products_by_category, get_product_by_id,
    get_all_categories_sales
)
from extensions import BOT_USERNAME
from config import CONTACT_BOT_URL, CONTACT_WHATSAPP
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
    
    # 3. جلب عدد المبيعات لكل فئة
    sales_counts = get_all_categories_sales()
    
    for cat in categories:
        products = get_products_by_category(cat.get('name', ''))
        cat['products_count'] = len(products)
        cat['sales_count'] = sales_counts.get(cat.get('name', ''), 0)
    
    # 4. جلب عدد منتجات السلة
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
                         cart_count=cart_count,
                         bot_username=BOT_USERNAME,
                         contact_bot_url=CONTACT_BOT_URL,
                         contact_whatsapp=CONTACT_WHATSAPP)

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
        try:
            balance = get_balance(user_id)
        except:
            balance = 0.0
    
    # جلب عدد السلة
    cart_count = 0
    if user_id:
        cart = get_user_cart(str(user_id)) or {}
        cart_count = len(cart.get('items', []))
    
    # جلب بيانات الفئة
    category = None
    categories = get_categories()
    for cat in categories:
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        # فئة غير موجودة
        category = {'id': category_id, 'name': 'فئة غير موجودة'}
    
    # جلب منتجات الفئة
    all_products = get_products_by_category(category.get('name', ''))
    
    # تصنيف المنتجات
    items = []  # المتاحة
    sold_items = []  # المباعة
    my_purchases = []  # مشتريات المستخدم
    
    for product in all_products:
        if product.get('sold'):
            # تحقق إذا كان المستخدم هو المشتري
            if user_id and str(product.get('buyer_id')) == str(user_id):
                my_purchases.append(product)
            else:
                sold_items.append(product)
        else:
            items.append(product)
    
    # تحضير JSON للفئات
    categories_json = json.dumps([{'id': c.get('id', ''), 'name': c.get('name', '')} for c in categories])
    
    return render_template('category.html',
                         category=category,
                         category_id=category_id,
                         items=items,
                         sold_items=sold_items,
                         my_purchases=my_purchases,
                         categories_json=categories_json,
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


# ===================== الصفحات القانونية والعامة =====================
from datetime import datetime

@web_bp.route('/privacy-policy')
def privacy_policy():
    """صفحة سياسة الخصوصية"""
    return render_template('pages/privacy.html', 
                          title="سياسة الخصوصية",
                          current_year=datetime.now().year)

@web_bp.route('/terms-of-service')
def terms_of_service():
    """صفحة شروط الاستخدام"""
    return render_template('pages/terms.html', 
                          title="شروط الاستخدام",
                          current_year=datetime.now().year)

@web_bp.route('/refund-policy')
def refund_policy():
    """صفحة سياسة الاسترجاع"""
    return render_template('pages/refund.html', 
                          title="سياسة الاسترجاع",
                          current_year=datetime.now().year)

@web_bp.route('/contact-us')
def contact_us():
    """صفحة اتصل بنا"""
    return render_template('pages/contact.html', 
                          title="اتصل بنا",
                          contact_bot_url=CONTACT_BOT_URL,
                          contact_whatsapp=CONTACT_WHATSAPP,
                          current_year=datetime.now().year)

@web_bp.route('/faq')
def faq():
    """صفحة الأسئلة الشائعة"""
    return render_template('pages/faq.html', 
                          title="الأسئلة الشائعة",
                          current_year=datetime.now().year)

