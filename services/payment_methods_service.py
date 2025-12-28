#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ميزة #6: خيارات دفع متعددة
===========================
"""

from flask import Blueprint, request, jsonify, session
from extensions import db
from firebase_utils import get_user_cart, get_balance

payment_bp = Blueprint('payment_options', __name__)

@payment_bp.route('/api/payment/methods', methods=['GET'])
def get_payment_methods():
    """جلب خيارات الدفع المتاحة للمستخدم"""
    user_id = session.get('user_id')
    balance = get_balance(user_id)
    
    # الخيارات الأساسية
    payment_methods = {
        'wallet': {
            'name': '💰 من المحفظة',
            'description': 'الدفع من رصيدك الحالي',
            'balance': balance,
            'available': balance > 0,
            'icon': '💳'
        },
        'card': {
            'name': '🏦 بطاقة ائتمان',
            'description': 'بطاقة فيزا أو ماستركارد',
            'available': True,
            'icon': '🏦',
            'fee': 0  # بدون رسوم
        },
        'installments': {
            'name': '📅 تقسيط (3 أشهر)',
            'description': 'ادفع على 3 دفعات بدون فائدة',
            'available': True,
            'icon': '📅',
            'min_amount': 100,
            'monthly_payment': 'سيتم حسابها'
        }
    }
    
    return jsonify({
        'status': 'success',
        'payment_methods': payment_methods,
        'current_balance': balance
    })

@payment_bp.route('/api/payment/process', methods=['POST'])
def process_payment():
    """معالجة الدفع حسب الطريقة المختارة"""
    data = request.json
    user_id = str(data.get('user_id'))
    payment_method = data.get('payment_method')  # wallet, card, installments
    total_amount = float(data.get('total_amount'))
    
    print(f"💳 طريقة الدفع: {payment_method}")
    print(f"💰 المبلغ: {total_amount}")
    
    if payment_method == 'wallet':
        # ✅ الدفع من المحفظة
        return process_wallet_payment(user_id, total_amount)
    
    elif payment_method == 'card':
        # ✅ الدفع بالبطاقة
        return process_card_payment(user_id, total_amount)
    
    elif payment_method == 'installments':
        # ✅ الدفع بالتقسيط
        return process_installment_payment(user_id, total_amount)
    
    return jsonify({'status': 'error', 'message': 'طريقة دفع غير معروفة'})

def process_wallet_payment(user_id, amount):
    """معالجة الدفع من المحفظة"""
    balance = get_balance(user_id)
    
    if balance < amount:
        return jsonify({
            'status': 'error',
            'message': f'رصيدك غير كافي! تحتاج {amount - balance} ريال إضافي',
            'shortage': amount - balance
        })
    
    # خصم المبلغ
    from firebase_utils import deduct_balance
    deduct_balance(user_id, amount)
    
    print(f"✅ تم الدفع من المحفظة: {amount} ريال")
    
    return jsonify({
        'status': 'success',
        'message': '✅ تم الدفع بنجاح من المحفظة!',
        'payment_method': 'wallet',
        'amount': amount,
        'new_balance': balance - amount
    })

def process_card_payment(user_id, amount):
    """معالجة الدفع بالبطاقة الائتمانية"""
    import uuid
    
    # إنشاء معرف فريد للمعاملة
    transaction_id = str(uuid.uuid4())
    
    # حفظ المعاملة في Firebase
    db.collection('transactions').document(transaction_id).set({
        'user_id': user_id,
        'type': 'card',
        'amount': amount,
        'status': 'pending',
        'created_at': db.server_timestamp()
    })
    
    print(f"💳 تحويل إلى بوابة الدفع: {transaction_id}")
    
    return jsonify({
        'status': 'success',
        'message': 'تحويل إلى بوابة الدفع...',
        'payment_method': 'card',
        'transaction_id': transaction_id,
        'redirect_url': f'/payment/gateway?transaction_id={transaction_id}'
    })

def process_installment_payment(user_id, amount):
    """معالجة الدفع بالتقسيط"""
    monthly_payment = amount / 3
    
    # حفظ خطة التقسيط
    installment_id = db.collection('installments').add({
        'user_id': user_id,
        'total_amount': amount,
        'monthly_payment': monthly_payment,
        'months': 3,
        'paid_months': 0,
        'status': 'active',
        'created_at': db.server_timestamp()
    })[1].id
    
    print(f"📅 خطة تقسيط: {monthly_payment} ريال × 3 شهور")
    
    return jsonify({
        'status': 'success',
        'message': 'تم إعداد خطة التقسيط بنجاح!',
        'payment_method': 'installments',
        'installment_id': installment_id,
        'total_amount': amount,
        'monthly_payment': monthly_payment,
        'months': 3
    })
