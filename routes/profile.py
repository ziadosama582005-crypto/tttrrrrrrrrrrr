"""
Profile Routes - مسارات صفحة الحساب الشخصي
"""
from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from extensions import db, logger
import json
from datetime import datetime

profile_bp = Blueprint('profile', __name__)

@profile_bp.route('/profile')
def profile():
    """صفحة الحساب الشخصي"""
    try:
        # التحقق من تسجيل الدخول
        if 'user_id' not in session or not session['user_id']:
            return redirect(url_for('auth.login_page'))
        
        user_id = session['user_id']
        
        # جلب بيانات المستخدم
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return redirect(url_for('auth.login_page'))
        
        user_data = user_doc.to_dict()
        
        # جلب آخر 3 طلبات من collection('orders')
        orders = []
        try:
            # جلب جميع الطلبات مرتبة حسب التاريخ (بدون where للتجنب من الحاجة للـ index)
            # ثم تصفيتها في الكود
            orders_query = db.collection('orders').order_by(
                'created_at', direction='DESCENDING'
            ).limit(100)  # جلب 100 لأننا سنصفيها
            
            orders_docs = orders_query.stream()
            
            for order_doc in orders_docs:
                order_data = order_doc.to_dict()
                # تصفية حسب buyer_id
                if order_data.get('buyer_id') == user_id:
                    orders.append({
                        'id': order_doc.id,
                        'product_name': order_data.get('item_name', 'منتج'),
                        'price': order_data.get('price', 0),
                        'status': order_data.get('status', 'pending'),
                        'created_at': order_data.get('created_at'),
                        'quantity': 1,
                        'total': order_data.get('price', 0),
                        'payment_method': order_data.get('payment_method', 'wallet')
                    })
                    # توقف بعد جلب 3 طلبات
                    if len(orders) >= 3:
                        break
        except Exception as e:
            logger.error(f"خطأ في جلب الطلبات: {e}")
            orders = []
        
        # تحويل التواريخ إلى صيغة محلية
        for order in orders:
            if order.get('created_at'):
                try:
                    # تحويل Timestamp إلى datetime
                    timestamp = order['created_at']
                    if hasattr(timestamp, 'strftime'):
                        order['date_formatted'] = timestamp.strftime('%d/%m/%Y %H:%M')
                    else:
                        order['date_formatted'] = str(timestamp)
                except:
                    order['date_formatted'] = str(order.get('created_at', ''))
        
        # حالة الطلب بصيغة عربية
        status_map = {
            'pending': '⏳ قيد الانتظار',
            'completed': '✅ مكتمل',
            'failed': '❌ فشل',
            'refunded': '🔄 مسترجع',
            'processing': '⚙️ قيد المعالجة',
            'delivered': '📦 تم التسليم'
        }
        
        for order in orders:
            order['status_ar'] = status_map.get(order.get('status'), 'غير معروف')
        
        # التحقق من وجود الصورة
        profile_photo = user_data.get('profile_photo', '')
        
        return render_template('profile.html',
            user_name=user_data.get('name', 'المستخدم'),
            user_id=user_id,
            profile_photo=profile_photo,
            balance=user_data.get('balance', 0),
            orders=orders
        )
    
    except Exception as e:
        logger.error(f"خطأ في صفحة الحساب: {e}")
        return redirect(url_for('auth.login_page'))


@profile_bp.route('/api/profile')
def api_profile():
    """API لجلب بيانات الحساب"""
    try:
        if 'user_id' not in session or not session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        
        user_id = session['user_id']
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        
        user_data = user_doc.to_dict()
        
        return jsonify({
            'user_id': user_id,
            'name': user_data.get('name', ''),
            'profile_photo': user_data.get('profile_photo', ''),
            'balance': user_data.get('balance', 0)
        })
    
    except Exception as e:
        logger.error(f"خطأ في API الحساب: {e}")
        return jsonify({'error': str(e)}), 500
