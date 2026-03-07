#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام الدفع EdfaPay
==================
جميع دوال التعامل مع بوابة الدفع
"""

import hashlib
import time
import requests

from config import EDFAPAY_MERCHANT_ID, EDFAPAY_PASSWORD, EDFAPAY_API_URL, SITE_URL

# === دوال مساعدة ===

def calculate_hash(order_id, amount, description):
    """حساب الـ Hash لـ EdfaPay"""
    to_hash = f"{order_id}{amount}SAR{description}{EDFAPAY_PASSWORD}".upper()
    md5_hash = hashlib.md5(to_hash.encode()).hexdigest()
    final_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
    return final_hash

def create_payment_payload(order_id, amount, description, user_id, user_name='Customer', phone='966500000000'):
    """إنشاء بيانات طلب الدفع"""
    final_hash = calculate_hash(order_id, amount, description)
    
    return {
        'action': 'SALE',
        'edfa_merchant_id': EDFAPAY_MERCHANT_ID,
        'order_id': order_id,
        'order_amount': str(amount),
        'order_currency': 'SAR',
        'order_description': description,
        'req_token': 'N',
        'payer_first_name': user_name or 'Customer',
        'payer_last_name': 'User',
        'payer_address': 'Riyadh',
        'payer_country': 'SA',
        'payer_city': 'Riyadh',
        'payer_zip': '12221',
        'payer_email': f'user{user_id}@telegram.com',
        'payer_phone': phone,
        'payer_ip': '176.44.76.222',
        'term_url_3ds': f"{SITE_URL}/payment/success?order_id={order_id}",
        'checkout_expiry_mins': '60',
        'auth': 'N',
        'recurring_init': 'N',
        'hash': final_hash
    }

# === دوال الدفع ===

def create_edfapay_invoice(user_id, amount, user_name='Customer'):
    """إنشاء فاتورة دفع في EdfaPay"""
    try:
        # توليد معرف فريد للطلب
        order_id = f"TR{user_id}{int(time.time())}"
        order_description = f"Recharge {amount} SAR"
        
        # إنشاء الـ payload
        payload = create_payment_payload(
            order_id=order_id,
            amount=amount,
            description=order_description,
            user_id=user_id,
            user_name=user_name
        )
        
        print(f"📤 EdfaPay Request: {payload}")
        
        # إرسال الطلب
        response = requests.post(EDFAPAY_API_URL, data=payload, timeout=30)
        print(f"📤 EdfaPay Response Status: {response.status_code}")
        print(f"📤 EdfaPay Response: {response.text[:500]}")
        
        result = response.json()
        
        # التحقق من النجاح
        if response.status_code == 200 and result.get('redirect_url'):
            return {
                'success': True,
                'payment_url': result.get('redirect_url'),
                'order_id': order_id
            }
        else:
            error_msg = result.get('message') or result.get('error') or result.get('errors') or result
            print(f"❌ EdfaPay Error: {error_msg}")
            return {
                'success': False,
                'error': str(error_msg)
            }
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'انتهت مهلة الاتصال'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': f'خطأ في الاتصال: {str(e)}'}
    except Exception as e:
        print(f"❌ Exception in create_edfapay_invoice: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

def create_wallet_payment(user_id, amount):
    """إنشاء طلب شحن رصيد من الموقع"""
    try:
        amount_int = int(amount)
        order_id = f"TR{user_id}{int(time.time())}"
        order_description = f"Recharge {amount_int} SAR"
        
        # إنشاء الـ payload
        payload = create_payment_payload(
            order_id=order_id,
            amount=amount_int,
            description=order_description,
            user_id=user_id
        )
        
        print(f"📤 Wallet Pay Request: {payload}")
        
        response = requests.post(EDFAPAY_API_URL, data=payload, timeout=30)
        print(f"📥 EdfaPay Raw Response: {response.text}")
        
        try:
            result = response.json()
        except:
            print(f"❌ فشل في تحليل JSON: {response.text}")
            return {'success': False, 'error': 'خطأ في بوابة الدفع - حاول مرة أخرى'}
        
        print(f"📥 EdfaPay Response: {result}")
        
        if response.status_code == 200 and result.get('redirect_url'):
            return {
                'success': True,
                'payment_url': result.get('redirect_url'),
                'order_id': order_id,
                'amount': amount_int
            }
        else:
            error_msg = result.get('message') or result.get('error') or result.get('error_message') or 'فشل في إنشاء طلب الدفع'
            print(f"❌ EdfaPay Error: {error_msg}")
            return {'success': False, 'error': error_msg}
            
    except requests.exceptions.Timeout:
        print(f"❌ Wallet Pay Timeout")
        return {'success': False, 'error': 'انتهى وقت الاتصال - حاول مرة أخرى'}
    except requests.exceptions.RequestException as e:
        print(f"❌ Wallet Pay Request Error: {e}")
        return {'success': False, 'error': 'خطأ في الاتصال ببوابة الدفع'}
    except Exception as e:
        print(f"❌ Wallet Pay Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': f'حدث خطأ: {str(e)}'}

def register_callback_url():
    """تسجيل رابط الـ webhook في EdfaPay"""
    if not EDFAPAY_MERCHANT_ID:
        print("⚠️ لا يوجد MERCHANT_ID لتسجيل الـ callback")
        return False
    
    try:
        callback_url = f"{SITE_URL}/payment/edfapay_webhook"
        
        response = requests.post(
            "https://api.edfapay.com/payment/merchants/callback-url",
            json={
                "action": "post",
                "id": EDFAPAY_MERCHANT_ID,
                "url": callback_url
            },
            timeout=30
        )
        
        print(f"📡 تسجيل Callback URL: {response.status_code}")
        print(f"📡 Response: {response.text}")
        
        if response.status_code == 200:
            print(f"✅ تم تسجيل Callback URL: {callback_url}")
            return True
        else:
            print(f"❌ فشل تسجيل Callback URL")
            return False
    except Exception as e:
        print(f"❌ خطأ في تسجيل Callback: {e}")
        return False

def check_callback_url():
    """التحقق من رابط الـ webhook المسجل في EdfaPay"""
    if not EDFAPAY_MERCHANT_ID:
        return None
    
    try:
        response = requests.post(
            "https://api.edfapay.com/payment/merchants/callback-url",
            json={
                "action": "get",
                "id": EDFAPAY_MERCHANT_ID
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"❌ خطأ في التحقق من Callback: {e}")
        return None

# === الحالات الناجحة والفاشلة ===
SUCCESS_STATUSES = ['SUCCESS', 'SETTLED', 'CAPTURED', 'APPROVED', '3DS_SUCCESS']
FAILED_STATUSES = ['DECLINED', 'FAILURE', 'FAILED', 'TXN_FAILURE', 'REJECTED', 'CANCELLED', 'ERROR', '3DS_FAILURE']
PENDING_STATUSES = ['PENDING', 'PROCESSING', 'REDIRECT', '3DS_REQUIRED']

def is_payment_successful(status):
    """التحقق من نجاح الدفع"""
    return str(status).upper().strip() in SUCCESS_STATUSES

def is_payment_failed(status):
    """التحقق من فشل الدفع"""
    return str(status).upper().strip() in FAILED_STATUSES

def is_payment_pending(status):
    """التحقق من أن الدفع معلق"""
    return str(status).upper().strip() in PENDING_STATUSES
