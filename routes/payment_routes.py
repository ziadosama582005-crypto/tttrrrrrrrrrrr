# ============================================
# === routes/payment_routes.py ===
# === مسارات الدفع والفواتير ===
# ============================================

from flask import Blueprint, render_template, redirect, request, jsonify
import time
from extensions import db, BOT_USERNAME, logger

# استيراد الدوال المطلوبة
from telegram.bot_handlers import create_customer_invoice

payment_bp = Blueprint('payment', __name__)

# تخزين الفواتير في الذاكرة (يُستورد من app.py)
merchant_invoices = {}

def set_merchant_invoices(invoices_dict):
    """تعيين قاموس الفواتير من app.py"""
    global merchant_invoices
    merchant_invoices = invoices_dict


# ============ صفحة الفاتورة للعميل ============
@payment_bp.route('/invoice/<invoice_id>')
def show_invoice(invoice_id):
    """عرض صفحة الفاتورة للعميل"""
    
    # البحث عن الفاتورة في الذاكرة
    invoice_data = merchant_invoices.get(invoice_id)
    
    # البحث في Firebase إذا لم توجد
    if not invoice_data:
        try:
            doc = db.collection('merchant_invoices').document(invoice_id).get()
            if doc.exists:
                invoice_data = doc.to_dict()
                merchant_invoices[invoice_id] = invoice_data
        except Exception as e:
            print(f"⚠️ خطأ في جلب الفاتورة: {e}")
    
    # إذا لم توجد الفاتورة
    if not invoice_data:
        return render_template('invoice/not_found.html'), 404
    
    # التحقق من انتهاء صلاحية الفاتورة (ساعة واحدة)
    expires_at = invoice_data.get('expires_at', 0)
    current_time = time.time()
    
    # إذا انتهت صلاحية الفاتورة
    if expires_at > 0 and current_time > expires_at and invoice_data.get('status') != 'completed':
        # تحديث الحالة إلى منتهية
        try:
            invoice_data['status'] = 'expired'
            merchant_invoices[invoice_id] = invoice_data
            db.collection('merchant_invoices').document(invoice_id).update({'status': 'expired'})
        except:
            pass
        
        return render_template('invoice/expired.html', 
            invoice_id=invoice_id, 
            amount=invoice_data.get('amount', 0)), 410
    
    # إذا كانت الفاتورة مرفوضة أو فاشلة
    if invoice_data.get('status') in ['failed', 'declined']:
        return render_template('invoice/declined.html',
            invoice_id=invoice_id,
            amount=invoice_data.get('amount', 0)), 410
    
    # إذا كانت الفاتورة مدفوعة مسبقاً
    if invoice_data.get('status') == 'completed':
        return render_template('invoice/paid.html')
    
    # عرض صفحة الفاتورة
    merchant_name = invoice_data.get('merchant_name', 'التاجر')
    amount = invoice_data.get('amount', 0)
    
    # جلب وقت الانتهاء المحفوظ
    expires_at_ts = invoice_data.get('expires_at')
    if not expires_at_ts:
        created_at = invoice_data.get('created_at')
        if created_at:
            if hasattr(created_at, 'timestamp'):
                expires_at_ts = created_at.timestamp() + 3600
            elif isinstance(created_at, (int, float)):
                expires_at_ts = created_at + 3600
            else:
                expires_at_ts = time.time()
        else:
            expires_at_ts = time.time()
    
    remaining_seconds = int(expires_at_ts - time.time())
    if remaining_seconds < 0:
        remaining_seconds = 0
    
    return render_template('invoice/show.html',
        merchant_name=merchant_name,
        amount=amount,
        invoice_id=invoice_id,
        remaining_seconds=remaining_seconds)


@payment_bp.route('/invoice/<invoice_id>/pay', methods=['POST'])
def process_invoice_payment(invoice_id):
    """معالجة دفع الفاتورة"""
    
    # جلب رقم الهاتف الكامل (مع رمز الدولة)
    phone = request.form.get('full_phone', '').strip()
    if not phone:
        phone = request.form.get('phone', '').strip()
    
    # البحث عن الفاتورة
    invoice_data = merchant_invoices.get(invoice_id)
    
    if not invoice_data:
        try:
            doc = db.collection('merchant_invoices').document(invoice_id).get()
            if doc.exists:
                invoice_data = doc.to_dict()
        except:
            pass
    
    if not invoice_data:
        return redirect(f'/invoice/{invoice_id}')
    
    # التحقق من انتهاء صلاحية الفاتورة
    expires_at = invoice_data.get('expires_at', 0)
    if expires_at > 0 and time.time() > expires_at:
        return redirect(f'/invoice/{invoice_id}')
    
    # التحقق من أن الفاتورة لم تدفع
    if invoice_data.get('status') == 'completed':
        return redirect(f'/invoice/{invoice_id}')
    
    # إنشاء طلب الدفع
    merchant_id = invoice_data.get('merchant_id')
    merchant_name = invoice_data.get('merchant_name')
    amount = invoice_data.get('amount')
    
    result = create_customer_invoice(merchant_id, merchant_name, amount, phone, invoice_id)
    
    if result['success']:
        # تحديث الفاتورة الأصلية
        try:
            merchant_invoices[invoice_id]['customer_phone'] = phone
            merchant_invoices[invoice_id]['order_id'] = result['order_id']
            
            db.collection('merchant_invoices').document(invoice_id).update({
                'customer_phone': phone,
                'order_id': result['order_id']
            })
        except:
            pass
        
        return redirect(result['payment_url'])
    else:
        return render_template('invoice/error.html',
            error=result.get('error', 'خطأ غير معروف'),
            invoice_id=invoice_id)


@payment_bp.route('/payment/success', methods=['GET', 'POST'])
def payment_success():
    """صفحة نتيجة الدفع - تتحقق من الحالة الفعلية"""
    
    data = {}
    if request.method == 'POST':
        data = request.form.to_dict() or request.json or {}
    else:
        data = request.args.to_dict() or {}
    
    print(f"📄 Payment Result Page: {data}")
    
    status = data.get('status', '') or data.get('result', '')
    order_id = data.get('order_id', '')
    decline_reason = data.get('decline_reason', '')
    
    status_upper = str(status).upper().strip()
    
    SUCCESS_STATUSES = ['SUCCESS', 'SETTLED', 'CAPTURED', 'APPROVED', '3DS_SUCCESS']
    FAILED_STATUSES = ['DECLINED', 'FAILURE', 'FAILED', 'TXN_FAILURE', 'REJECTED', 'CANCELLED', 'ERROR', '3DS_FAILURE']
    
    is_success = status_upper in SUCCESS_STATUSES
    is_failed = status_upper in FAILED_STATUSES
    
    result = data.get('result', '').upper()
    if result == 'DECLINED' or result == 'FAILURE':
        is_success = False
        is_failed = True
    
    # التحقق من Firebase
    if not status and order_id:
        try:
            doc = db.collection('pending_payments').document(order_id).get()
            if doc.exists:
                payment_data = doc.to_dict()
                payment_status = payment_data.get('status', '')
                if payment_status == 'completed':
                    is_success = True
                    is_failed = False
                elif payment_status == 'failed':
                    is_success = False
                    is_failed = True
                    decline_reason = payment_data.get('failure_reason', 'فشلت العملية')
        except Exception as e:
            print(f"⚠️ خطأ في التحقق من Firebase: {e}")
    
    if is_success:
        return render_template('payment/success.html', bot_username=BOT_USERNAME)
    elif is_failed:
        error_msg = decline_reason or status or "فشلت عملية الدفع"
        return render_template('payment/failed.html', 
            bot_username=BOT_USERNAME, 
            error_msg=error_msg)
    else:
        return render_template('payment/pending.html',
            bot_username=BOT_USERNAME,
            order_id=order_id)


@payment_bp.route('/payment/cancel')
def payment_cancel():
    """صفحة إلغاء الدفع"""
    return render_template('payment/cancel.html', bot_username=BOT_USERNAME)
