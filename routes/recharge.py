# نسخ من wallet routes
from flask import Blueprint, render_template, request, jsonify
import time
import uuid
from extensions import db, logger
from firebase_utils import get_balance, add_balance
from payment import create_wallet_payment
from notifications import notify_new_charge

recharge_bp = Blueprint('recharge', __name__, url_prefix='/wallet')

# تخزين الفواتير
merchant_invoices = {}

# ============ عرض صفحة الشحن ============
@recharge_bp.route('/recharge')
def recharge_page():
    """عرض صفحة الشحن الجديدة"""
    return render_template('recharge.html')

# ============ API: جلب الرصيد ============
@recharge_bp.route('/api/balance')
def get_wallet_balance():
    """جلب رصيد الحساب الحالي"""
    try:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'غير مصرح'}), 401
        
        user_id = str(current_user.id)
        balance = get_balance(user_id)
        
        return jsonify({
            'success': True,
            'balance': balance,
            'currency': 'SAR'
        })
    except Exception as e:
        logger.error(f"خطأ في جلب الرصيد: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ============ شحن مباشر (الطريقة الحالية) ============
@recharge_bp.route('/recharge', methods=['POST'])
def direct_recharge():
    """شحن مباشر من EdfaPay"""
    try:
        from flask_login import current_user
        
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'غير مصرح'})
        
        # قراءة البيانات من JSON أو form
        data = request.get_json() or request.form
        amount = str(data.get('amount', '')).strip()
        user_id = str(current_user.id)
        user_name = current_user.username or f"User {user_id}"
        
        # التحقق من المبلغ
        if not amount:
            return jsonify({'success': False, 'error': 'المبلغ مطلوب'})
        
        try:
            amount_int = int(float(amount))
            if amount_int < 10 or amount_int > 50000:
                return jsonify({'success': False, 'error': 'المبلغ يجب أن يكون بين 10 و 50000 ريال'})
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'المبلغ يجب أن يكون رقماً'})
        
        # إنشاء طلب دفع في EdfaPay
        result = create_wallet_payment(user_id, amount_int)
        
        if result['success']:
            # إشعار المالك
            notify_new_charge(user_id, amount_int, method='edfapay', username=user_name, async_mode=True)
            
            return jsonify({
                'success': True,
                'payment_url': result['payment_url'],
                'order_id': result.get('order_id')
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'فشل إنشاء طلب الدفع')
            })
    
    except Exception as e:
        logger.error(f"❌ خطأ في direct_recharge: {e}")
        return jsonify({'success': False, 'error': 'حدث خطأ على السيرفر'})

# ============ إنشاء رابط شحن (جديد) ============
@recharge_bp.route('/create-link', methods=['POST'])
def create_recharge_link():
    """إنشاء رابط شحن يشاركه أي شخص"""
    try:
        from flask_login import current_user
        
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'غير مصرح'})
        
        # قراءة البيانات من JSON أو form
        data = request.get_json() or request.form
        amount = str(data.get('amount', '')).strip()
        user_id = str(current_user.id)
        user_name = current_user.username or f"User {user_id}"
        
        # التحقق من المبلغ
        if not amount:
            return jsonify({'success': False, 'error': 'المبلغ مطلوب'})
        
        try:
            amount_int = int(float(amount))
            if amount_int < 10 or amount_int > 50000:
                return jsonify({'success': False, 'error': 'المبلغ يجب أن يكون بين 10 و 50000 ريال'})
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'المبلغ يجب أن يكون رقماً'})
        
        # إنشاء معرف فريد للفاتورة
        invoice_id = f"LINK_{int(time.time())}_{user_id}_{uuid.uuid4().hex[:6]}"
        
        # بيانات الفاتورة
        invoice_data = {
            'invoice_id': invoice_id,
            'recipient_id': user_id,                   # من سينال الرصيد
            'recipient_name': user_name,
            'amount': amount_int,
            'status': 'pending',
            'created_at': time.time(),
            'expires_at': time.time() + 3600,          # ساعة واحدة
            'is_recharge_link': True,                  # تمييز الرابط
            'created_by': user_id,
            'description': f"رابط شحن من {user_name}"
        }
        
        # حفظ في Firebase
        try:
            db.collection('merchant_invoices').document(invoice_id).set(invoice_data)
            merchant_invoices[invoice_id] = invoice_data
        except Exception as e:
            logger.error(f"خطأ في حفظ في Firebase: {e}")
            return jsonify({'success': False, 'error': 'خطأ في حفظ الرابط'})
        
        # إنشاء الرابط
        from extensions import SITE_URL
        link = f"{SITE_URL}/invoice/{invoice_id}"
        
        return jsonify({
            'success': True,
            'link': link,
            'invoice_id': invoice_id,
            'amount': amount_int
        })
    
    except Exception as e:
        logger.error(f"❌ خطأ في create_recharge_link: {e}")
        return jsonify({'success': False, 'error': 'حدث خطأ على السيرفر'})
