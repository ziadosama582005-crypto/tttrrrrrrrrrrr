#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ميزة #23: اقتراح شحن الرصيد - عملية ذكية
==========================================
"""

from flask import Blueprint, request, jsonify, session
from extensions import db
from firebase_utils import get_user_cart, get_balance
from security_utils import require_session_user, get_session_user_id

charge_bp = Blueprint('charge_suggestion', __name__)

@charge_bp.route('/api/cart/check-balance', methods=['GET'])
@require_session_user()
def check_balance_warning():
    """التحقق من الرصيد واقتراح الشحن إذا لزم الأمر"""
    user_id = get_session_user_id()
    cart = get_user_cart(user_id)
    balance = get_balance(user_id)
    
    if not cart or not cart.get('items'):
        return jsonify({'status': 'ok', 'message': 'السلة فارغة'})
    
    # حساب الإجمالي
    total = sum(float(item.get('price', 0)) for item in cart.get('items', []))
    
    print(f"💰 الرصيد: {balance} | الإجمالي: {total}")
    
    response = {
        'user_id': user_id,
        'current_balance': balance,
        'cart_total': total,
        'is_sufficient': balance >= total,
        'shortage': max(0, total - balance),
        'warnings': [],
        'suggestions': []
    }
    
    # ✅ حالة 1: الرصيد كافي
    if balance >= total:
        response['status'] = 'sufficient'
        response['message'] = '✅ رصيدك كافي للشراء'
        return jsonify(response)
    
    # ⚠️ حالة 2: الرصيد غير كافي
    shortage = total - balance
    response['status'] = 'insufficient'
    response['warnings'].append({
        'type': 'warning',
        'title': '⚠️ رصيد غير كافي',
        'message': f'تحتاج إلى {shortage:.2f} ريال إضافي',
        'severity': 'high'
    })
    
    # 🎁 الاقتراحات الذكية
    response['suggestions'] = generate_smart_suggestions(user_id, shortage, balance)
    
    return jsonify(response)

def generate_smart_suggestions(user_id, shortage, current_balance):
    """توليد اقتراحات ذكية لشحن الرصيد"""
    suggestions = []
    
    # 1️⃣ الاقتراح الأول: اشحن بالضبط ما تحتاج
    suggestions.append({
        'id': 'exact_amount',
        'type': 'recommended',
        'title': '💡 الخيار الأمثل',
        'description': f'اشحن {shortage:.2f} ريال فقط لإتمام الشراء',
        'amount': shortage,
        'icon': '✨',
        'priority': 1
    })
    
    # 2️⃣ الاقتراح الثاني: اشحن أكثر قليلاً لتوفير رصيد إضافي
    extra_amount = shortage + 50  # إضافة 50 ريال
    suggestions.append({
        'id': 'extra_amount',
        'type': 'offer',
        'title': '🎁 عرض خاص',
        'description': f'اشحن {extra_amount:.2f} ريال واحصل على رصيد إضافي {50:.2f} ريال لمشتريات المستقبل',
        'amount': extra_amount,
        'bonus': 50,
        'icon': '🎉',
        'priority': 2
    })
    
    # 3️⃣ الاقتراح الثالث: استخدم خيار دفع آخر
    suggestions.append({
        'id': 'alternate_payment',
        'type': 'alternative',
        'title': '💳 خيار آخر',
        'description': 'استخدم بطاقتك الائتمانية أو خيار التقسيط',
        'amount': None,
        'icon': '🏦',
        'priority': 3,
        'redirect': '/cart?payment_method=card'
    })
    
    # 4️⃣ إذا كان الرصيد منخفض جداً
    if current_balance < 10:
        suggestions.insert(0, {
            'id': 'low_balance_warning',
            'type': 'critical',
            'title': '🚨 تنبيه مهم',
            'message': f'رصيدك قليل جداً ({current_balance:.2f} ريال)',
            'description': f'اشحن الآن للحصول على عروض حصرية',
            'icon': '⚠️',
            'priority': 0
        })
    
    return suggestions

@charge_bp.route('/api/charge/recommended-amounts', methods=['GET'])
@require_session_user()
def recommended_charge_amounts():
    """الحصول على المبالغ الموصى بها للشحن"""
    user_id = get_session_user_id()
    balance = get_balance(user_id)
    
    # المبالغ الموصى بها حسب الرصيد الحالي
    recommended = []
    
    if balance < 50:
        recommended = [50, 100, 200]
        bonus_type = 'low_balance'  # خصم 10%
    elif balance < 200:
        recommended = [100, 200, 500]
        bonus_type = 'medium_balance'  # خصم 5%
    else:
        recommended = [200, 500, 1000]
        bonus_type = 'high_balance'  # بدون خصم
    
    # حساب الخصم/الهدية
    amounts = []
    for amount in recommended:
        bonus = 0
        discount = 0
        
        if bonus_type == 'low_balance':
            bonus = amount * 0.10  # 10% هدية
        elif bonus_type == 'medium_balance':
            bonus = amount * 0.05  # 5% هدية
        
        amounts.append({
            'amount': amount,
            'bonus': bonus,
            'total': amount + bonus,
            'badge': f'احصل على {bonus:.0f} ريال هدية!' if bonus > 0 else 'عادي'
        })
    
    return jsonify({
        'status': 'success',
        'current_balance': balance,
        'recommended_amounts': amounts,
        'bonus_type': bonus_type
    })

@charge_bp.route('/api/charge/quick-charge', methods=['POST'])
@require_session_user()
def quick_charge():
    """شحن سريع برقم واحد"""
    user_id = get_session_user_id()  # ✅ من Session فقط - لا نقبل user_id من الطلب
    data = request.json
    amount = float(data.get('amount', 0))
    
    print(f"⚡ شحن سريع: {amount} ريال")
    
    # حفظ طلب الشحن
    charge_id = db.collection('charge_requests').add({
        'user_id': user_id,
        'amount': amount,
        'status': 'pending',
        'created_at': db.server_timestamp()
    })[1].id
    
    return jsonify({
        'status': 'success',
        'message': f'✅ تم إرسال طلب شحن {amount} ريال',
        'charge_id': charge_id,
        'redirect_url': f'/payment/charge?id={charge_id}'
    })

@charge_bp.route('/api/charge/quick-links', methods=['GET'])
def get_quick_charge_links():
    """روابط سريعة للشحن"""
    return jsonify({
        'quick_links': [
            {
                'amount': 50,
                'label': '50 ريال',
                'emoji': '💚',
                'recommended': False
            },
            {
                'amount': 100,
                'label': '100 ريال',
                'emoji': '💜',
                'recommended': True
            },
            {
                'amount': 200,
                'label': '200 ريال',
                'emoji': '💛',
                'recommended': False
            },
            {
                'amount': 500,
                'label': '500 ريال',
                'emoji': '🎁',
                'recommended': False,
                'badge': '+50 ريال هدية'
            }
        ]
    })
