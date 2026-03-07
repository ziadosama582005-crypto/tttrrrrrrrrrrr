# ============================================
# 💰 نظام المحفظة والشحن
# ============================================

from flask import Blueprint, request, jsonify, session, redirect, render_template
from datetime import datetime, timedelta, timezone
import time
import hashlib
import requests

from extensions import db, FIREBASE_AVAILABLE
from firebase_utils import get_balance, add_balance, get_charge_key, use_charge_key, query_where
from google.cloud import firestore
from security_utils import (
    require_session_user, get_session_user_id, checkout_with_transaction,
    log_security_event, sanitize_error_message
)

# استيراد دوال التشفير
try:
    from encryption_utils import decrypt_data
    ENCRYPTION_AVAILABLE = True
except:
    decrypt_data = lambda x: x
    ENCRYPTION_AVAILABLE = False

# إنشاء Blueprint
wallet_bp = Blueprint('wallet', __name__)

# متغيرات EdfaPay (سيتم تعيينها من app.py)
EDFAPAY_MERCHANT_ID = None
EDFAPAY_PASSWORD = None
EDFAPAY_API_URL = None
SITE_URL = None
pending_payments = {}
limiter = None


def init_wallet(merchant_id, password, api_url, site_url, payments_dict, app_limiter):
    """تهيئة متغيرات المحفظة"""
    global EDFAPAY_MERCHANT_ID, EDFAPAY_PASSWORD, EDFAPAY_API_URL, SITE_URL, pending_payments, limiter
    EDFAPAY_MERCHANT_ID = merchant_id
    EDFAPAY_PASSWORD = password
    EDFAPAY_API_URL = api_url
    SITE_URL = site_url
    pending_payments = payments_dict
    limiter = app_limiter


@wallet_bp.route('/wallet')
def wallet_page():
    """صفحة المحفظة والشحن"""
    user_id = session.get('user_id')
    
    if not user_id:
        return redirect('/')
    
    # جلب الرصيد
    balance = get_balance(user_id)
    
    # جلب المعاملات من Firebase
    transactions = []
    total_charges = 0
    charges_count = 0
    purchases_count = 0
    
    try:
        # جلب الشحنات
        charges_ref = query_where(db.collection('charge_history'), 'user_id', '==', str(user_id))
        for doc in charges_ref.stream():
            data = doc.to_dict()
            amount = data.get('amount', 0)
            total_charges += amount
            charges_count += 1
            
            # تحويل timestamp لرقم
            ts = data.get('timestamp', 0)
            if hasattr(ts, 'timestamp'):
                ts = ts.timestamp()
            elif hasattr(ts, 'seconds'):
                ts = ts.seconds
            elif not isinstance(ts, (int, float)):
                ts = 0
            
            transactions.append({
                'type': 'income',
                'title': 'شحن رصيد',
                'amount': amount,
                'date': data.get('date', 'غير محدد'),
                'timestamp': ts
            })
        
        # جلب المشتريات
        orders_ref = query_where(db.collection('orders'), 'buyer_id', '==', str(user_id))
        for doc in orders_ref.stream():
            data = doc.to_dict()
            purchases_count += 1
            
            # تحويل التاريخ
            date_str = 'غير محدد'
            timestamp_val = 0
            if data.get('created_at'):
                try:
                    created = data['created_at']
                    if hasattr(created, 'seconds'):
                        timestamp_val = created.seconds
                        utc_time = datetime.fromtimestamp(created.seconds, tz=timezone.utc)
                        saudi_time = utc_time + timedelta(hours=3)
                        date_str = saudi_time.strftime('%Y-%m-%d %H:%M')
                    elif isinstance(created, datetime):
                        timestamp_val = created.timestamp()
                        saudi_time = created + timedelta(hours=3)
                        date_str = saudi_time.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            transactions.append({
                'type': 'expense',
                'title': f"شراء {data.get('item_name', 'منتج')}",
                'amount': data.get('price', 0),
                'date': date_str,
                'timestamp': timestamp_val
            })
        
        # ترتيب من الأحدث
        transactions.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        transactions = transactions[:15]
        
    except Exception as e:
        print(f"❌ خطأ في جلب المعاملات: {e}")
    
    return render_template('wallet.html', 
                          user_id=user_id,
                          balance=balance,
                          transactions=transactions,
                          total_charges=total_charges,
                          charges_count=charges_count,
                          purchases_count=purchases_count)


@wallet_bp.route('/wallet/pay', methods=['POST'])
@require_session_user()
def wallet_pay():
    """معالجة طلب الشحن من صفحة المحفظة - محمي من Authentication Bypass"""
    global pending_payments
    
    user_id = get_session_user_id()  # من Session فقط
    if not user_id:
        return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
    
    try:
        data = request.json
        phone = data.get('phone', '').strip()
        amount = float(data.get('amount', 0))
        
        if not phone or len(phone) < 10:
            return jsonify({'success': False, 'message': 'رقم جوال غير صحيح'})
        
        if amount < 10 or amount > 5000:
            return jsonify({'success': False, 'message': 'المبلغ يجب أن يكون بين 10 و 5000 ريال'})
        
        if not EDFAPAY_MERCHANT_ID or not EDFAPAY_PASSWORD:
            return jsonify({'success': False, 'message': 'بوابة الدفع غير مفعلة'})
        
        amount_int = int(amount)
        order_id = f"TR{user_id}{int(time.time())}"
        order_description = f"Recharge {amount_int} SAR"
        
        # حساب الـ hash
        to_hash = f"{order_id}{amount_int}SAR{order_description}{EDFAPAY_PASSWORD}".upper()
        md5_hash = hashlib.md5(to_hash.encode()).hexdigest()
        final_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
        
        # تسجيل الحدث
        log_security_event('WALLET_CHARGE_REQUEST', user_id, f'المبلغ: {amount_int}, الطلب: {order_id}')
        # تنسيق رقم الجوال
        formatted_phone = phone.replace('+', '').replace(' ', '')
        if formatted_phone.startswith('0'):
            formatted_phone = '966' + formatted_phone[1:]
        elif not formatted_phone.startswith('966'):
            formatted_phone = '966' + formatted_phone
        
        payload = {
            'action': 'SALE',
            'edfa_merchant_id': EDFAPAY_MERCHANT_ID,
            'order_id': order_id,
            'order_amount': str(amount_int),
            'order_currency': 'SAR',
            'order_description': order_description,
            'req_token': 'N',
            'payer_first_name': 'Customer',
            'payer_last_name': 'User',
            'payer_address': 'Riyadh',
            'payer_country': 'SA',
            'payer_city': 'Riyadh',
            'payer_zip': '12221',
            'payer_email': f'user{user_id}@telegram.com',
            'payer_phone': formatted_phone,
            'payer_ip': '176.44.76.222',
            'term_url_3ds': f"{SITE_URL}/payment/success?order_id={order_id}",
            'checkout_expiry_mins': '60',
            'auth': 'N',
            'recurring_init': 'N',
            'hash': final_hash
        }
        
        print(f"📤 Wallet Pay Request: {payload}")
        
        response = requests.post(EDFAPAY_API_URL, data=payload, timeout=30)
        
        print(f"📥 EdfaPay Raw Response: {response.text}")
        
        try:
            result = response.json()
        except:
            print(f"❌ فشل في تحليل JSON: {response.text}")
            return jsonify({'success': False, 'message': 'خطأ في بوابة الدفع - حاول مرة أخرى'})
        
        print(f"📥 EdfaPay Response: {result}")
        
        if response.status_code == 200 and result.get('redirect_url'):
            payment_url = result.get('redirect_url')
            
            # حفظ الطلب المعلق
            pending_payments[order_id] = {
                'user_id': str(user_id),
                'amount': amount,
                'order_id': order_id,
                'phone': phone,
                'payer_phone': formatted_phone,
                'status': 'pending',
                'created_at': time.time()
            }
            
            # حفظ في Firebase
            try:
                db.collection('pending_payments').document(order_id).set({
                    'user_id': str(user_id),
                    'amount': amount,
                    'order_id': order_id,
                    'phone': phone,
                    'payer_phone': formatted_phone,
                    'status': 'pending',
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"⚠️ خطأ في حفظ الطلب: {e}")
            
            return jsonify({
                'success': True,
                'payment_url': payment_url,
                'order_id': order_id
            })
        else:
            error_msg = result.get('message') or result.get('error') or result.get('error_message') or 'فشل في إنشاء طلب الدفع'
            print(f"❌ EdfaPay Error: {error_msg}")
            return jsonify({'success': False, 'message': error_msg})
            
    except requests.exceptions.Timeout:
        print(f"❌ Wallet Pay Timeout")
        return jsonify({'success': False, 'message': 'انتهى وقت الاتصال - حاول مرة أخرى'})
    except requests.exceptions.RequestException as e:
        print(f"❌ Wallet Pay Request Error: {e}")
        return jsonify({'success': False, 'message': 'خطأ في الاتصال ببوابة الدفع'})
    except Exception as e:
        print(f"❌ Wallet Pay Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})


@wallet_bp.route('/my_purchases')
@require_session_user()
def my_purchases_page():
    """صفحة مشترياتي - محمي"""
    user_id = get_session_user_id()
    
    purchases = []
    try:
        orders_ref = query_where(db.collection('orders'), 'buyer_id', '==', str(user_id))
        for doc in orders_ref.stream():
            data = doc.to_dict()
            data['id'] = doc.id
            
            # فك تشفير البيانات السرية
            if data.get('hidden_data'):
                try:
                    data['hidden_data'] = decrypt_data(data['hidden_data'])
                except Exception as e:
                    print(f"⚠️ خطأ في فك تشفير hidden_data: {e}")
                    # إذا فشل فك التشفير، ربما البيانات غير مشفرة أصلاً
                    pass
            
            if data.get('created_at'):
                try:
                    created = data['created_at']
                    if hasattr(created, 'seconds'):
                        utc_time = datetime.fromtimestamp(created.seconds, tz=timezone.utc)
                    elif isinstance(created, datetime):
                        utc_time = created
                    else:
                        utc_time = datetime.now(tz=timezone.utc)
                    
                    saudi_time = utc_time + timedelta(hours=3)
                    data['sold_at'] = saudi_time.strftime('%Y-%m-%d %H:%M')
                    data['sort_time'] = saudi_time.timestamp()
                except Exception as e:
                    print(f"خطأ في تحويل الوقت: {e}")
                    data['sold_at'] = 'غير محدد'
                    data['sort_time'] = 0
            else:
                data['sold_at'] = 'غير محدد'
                data['sort_time'] = 0
            purchases.append(data)
        
        purchases.sort(key=lambda x: x.get('sort_time', 0), reverse=True)
    except Exception as e:
        print(f"❌ خطأ في جلب المشتريات: {e}")
    
    return render_template('purchases.html', purchases=purchases)


@wallet_bp.route('/get_balance')
def get_balance_api():
    """جلب رصيد المستخدم"""
    user_id = session.get('user_id')
    
    if not user_id:
        return {'balance': 0}
    
    balance = get_balance(user_id)
    return {'balance': balance}


@wallet_bp.route('/charge_balance', methods=['POST'])
def charge_balance_api():
    """شحن الرصيد باستخدام كود الشحن - محمي من التخمين"""
    # ✅ Rate Limiting يدوي (3 محاولات في الدقيقة)
    from flask import request as req
    client_ip = req.headers.get('X-Forwarded-For', req.remote_addr)
    
    # تخزين محاولات الشحن (في الذاكرة)
    if not hasattr(charge_balance_api, 'attempts'):
        charge_balance_api.attempts = {}
    
    current_time = time.time()
    ip_key = f"charge_{client_ip}"
    
    # تنظيف المحاولات القديمة (أكثر من دقيقة)
    charge_balance_api.attempts = {k: v for k, v in charge_balance_api.attempts.items() if current_time - v['time'] < 60}
    
    # فحص عدد المحاولات
    if ip_key in charge_balance_api.attempts:
        if charge_balance_api.attempts[ip_key]['count'] >= 3:
            return jsonify({'success': False, 'message': '⏳ الرجاء الانتظار دقيقة قبل المحاولة مرة أخرى'}), 429
        charge_balance_api.attempts[ip_key]['count'] += 1
    else:
        charge_balance_api.attempts[ip_key] = {'count': 1, 'time': current_time}
    
    data = request.json
    key_code = data.get('charge_key', '').strip()
    
    if not session.get('user_id'):
        return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً!'})
    
    user_id = str(session.get('user_id'))
    
    if not key_code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال كود الشحن'})
    
    # البحث عن الكود في Firebase
    key_data = get_charge_key(key_code)
    
    if not key_data:
        return jsonify({'success': False, 'message': 'كود الشحن غير صحيح أو غير موجود'})
    
    if key_data.get('used', False):
        return jsonify({'success': False, 'message': 'هذا الكود تم استخدامه مسبقاً'})
    
    # شحن الرصيد
    amount = key_data.get('amount', 0)
    new_balance = add_balance(user_id, amount)
    
    # تحديث الكود كمستخدم
    use_charge_key(key_code, user_id)
    
    # حفظ سجل الشحنة
    if db:
        try:
            db.collection('charge_history').add({
                'user_id': user_id,
                'amount': amount,
                'key_code': key_code,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'timestamp': time.time(),
                'type': 'charge'
            })
        except Exception as e:
            print(f"خطأ في حفظ سجل الشحن: {e}")
    
    return jsonify({
        'success': True, 
        'message': f'تم شحن {amount} ريال بنجاح!',
        'new_balance': new_balance
    })
