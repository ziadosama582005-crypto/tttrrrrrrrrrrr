# -*- coding: utf-8 -*-
"""
نظام إشعارات المالك والمشرفين
يُستخدم لإرسال إشعارات تلقائية بجميع العمليات المهمة
"""

import logging
from extensions import bot, BOT_ACTIVE, ADMIN_ID, db

try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    USE_FIELD_FILTER = True
except ImportError:
    USE_FIELD_FILTER = False

logger = logging.getLogger(__name__)


def notify_owner(message, parse_mode='HTML'):
    """
    إرسال إشعار للمالك الرئيسي
    
    Args:
        message: نص الرسالة (يدعم HTML)
        parse_mode: نوع التنسيق (HTML أو Markdown)
    
    Returns:
        bool: True إذا تم الإرسال بنجاح
    """
    try:
        if BOT_ACTIVE and bot and ADMIN_ID:
            bot.send_message(ADMIN_ID, message, parse_mode=parse_mode)
            print(f"📨 تم إرسال إشعار للمالك")
            return True
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")
        print(f"❌ خطأ في إشعار المالك: {e}")
    return False


def notify_all_admins(message, parse_mode='HTML'):
    """
    إرسال إشعار لجميع المشرفين والمالك
    
    Args:
        message: نص الرسالة
        parse_mode: نوع التنسيق
    
    Returns:
        int: عدد المشرفين الذين تم إشعارهم
    """
    notified = 0
    
    try:
        # إشعار المالك أولاً
        if notify_owner(message, parse_mode):
            notified += 1
        
        # إشعار بقية المشرفين
        if db and BOT_ACTIVE and bot:
            admins = db.collection('admins').stream()
            for admin_doc in admins:
                admin_data = admin_doc.to_dict()
                try:
                    bot.send_message(int(admin_data['telegram_id']), message, parse_mode=parse_mode)
                    notified += 1
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_data.get('telegram_id')}: {e}")
        
        return notified
    except Exception as e:
        logger.error(f"Error notifying admins: {e}")
    return notified


def is_admin_or_owner(telegram_id):
    """
    التحقق إذا كان المستخدم مالك أو مشرف
    
    Args:
        telegram_id: معرف التليجرام
    
    Returns:
        bool: True إذا كان مشرف أو مالك
    """
    try:
        # المالك الرئيسي
        if int(telegram_id) == ADMIN_ID:
            return True
        
        # التحقق من جدول المشرفين
        if db:
            if USE_FIELD_FILTER:
                admins = db.collection('admins').where(filter=FieldFilter('telegram_id', '==', str(telegram_id))).get()
            else:
                admins = db.collection('admins').where('telegram_id', '==', str(telegram_id)).get()
            return len(list(admins)) > 0
        
        return False
    except:
        return False


# ===================== إشعارات محددة =====================

def notify_new_charge(user_id, amount, method='edfapay', username=None):
    """إشعار بشحن رصيد جديد"""
    method_names = {
        'edfapay': '💳 EdfaPay',
        'key': '🔑 كود شحن',
        'admin': '👨‍💼 من الإدارة',
        'telegram_key': '🔑 كود تليجرام'
    }
    
    message = (
        f"💰 <b>شحن رصيد جديد!</b>\n\n"
        f"👤 <b>المستخدم:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💵 <b>المبلغ:</b> {amount} ر.س\n"
        f"📍 <b>الطريقة:</b> {method_names.get(method, method)}"
    )
    return notify_owner(message)


def notify_withdrawal_request(user_id, amount, withdrawal_type, fee, net_amount, username=None):
    """إشعار بطلب سحب جديد"""
    type_names = {
        'normal': '⏳ سحب عادي (5.5%)',
        'instant': '⚡ سحب فوري (8%)'
    }
    
    message = (
        f"🏦 <b>طلب سحب جديد!</b>\n\n"
        f"👤 <b>المستخدم:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💵 <b>المبلغ:</b> {amount} ر.س\n"
        f"📍 <b>النوع:</b> {type_names.get(withdrawal_type, withdrawal_type)}\n"
        f"💸 <b>الرسوم:</b> {fee:.2f} ر.س\n"
        f"✅ <b>صافي المبلغ:</b> {net_amount:.2f} ر.س"
    )
    return notify_owner(message)


def notify_new_purchase(user_id, product_name, price, username=None):
    """إشعار بعملية شراء جديدة"""
    message = (
        f"🛒 <b>عملية شراء جديدة!</b>\n\n"
        f"👤 <b>المشتري:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>المنتج:</b> {product_name}\n"
        f"💰 <b>السعر:</b> {price} ر.س"
    )
    return notify_owner(message)


def notify_new_order(order_id, user_id, product_name, price, username=None):
    """إشعار بطلب جديد (سلة)"""
    message = (
        f"📋 <b>طلب جديد!</b>\n\n"
        f"📄 <b>رقم الطلب:</b> <code>{order_id}</code>\n"
        f"👤 <b>العميل:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>المنتج:</b> {product_name}\n"
        f"💰 <b>المبلغ:</b> {price} ر.س"
    )
    return notify_owner(message)


def notify_new_user(user_id, username=None, first_name=None):
    """إشعار بتسجيل مستخدم جديد"""
    message = (
        f"👋 <b>مستخدم جديد!</b>\n\n"
        f"👤 <b>الاسم:</b> {first_name or 'غير محدد'}\n"
        f"📱 <b>Username:</b> @{username or 'غير محدد'}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>"
    )
    return notify_owner(message)


def notify_admin_login(ip_address):
    """إشعار بتسجيل دخول الأدمن"""
    import time
    message = (
        f"🔐 <b>تسجيل دخول للوحة التحكم</b>\n\n"
        f"🌐 <b>IP:</b> <code>{ip_address}</code>\n"
        f"⏰ <b>الوقت:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return notify_owner(message)


def notify_product_added(product_name, price, category):
    """إشعار بإضافة منتج جديد"""
    message = (
        f"📦 <b>منتج جديد!</b>\n\n"
        f"📝 <b>الاسم:</b> {product_name}\n"
        f"💰 <b>السعر:</b> {price} ر.س\n"
        f"📁 <b>القسم:</b> {category}"
    )
    return notify_owner(message)


def notify_product_sold(product_name, price, buyer_id, buyer_name=None):
    """إشعار ببيع منتج"""
    message = (
        f"💵 <b>تم بيع منتج!</b>\n\n"
        f"📦 <b>المنتج:</b> {product_name}\n"
        f"💰 <b>السعر:</b> {price} ر.س\n"
        f"👤 <b>المشتري:</b> {buyer_name or buyer_id}\n"
        f"🆔 <b>ID:</b> <code>{buyer_id}</code>"
    )
    return notify_owner(message)


# ===================== إشعارات الفواتير والدفع =====================

def notify_invoice_created(merchant_id, merchant_name, amount, invoice_id, customer_phone=None):
    """إشعار بإنشاء فاتورة جديدة"""
    message = (
        f"🧾 <b>تم إنشاء فاتورة جديدة!</b>\n\n"
        f"👤 <b>التاجر:</b> {merchant_name}\n"
        f"🆔 <b>آيدي:</b> <code>{merchant_id}</code>\n"
        f"💰 <b>المبلغ:</b> {amount} ريال\n"
        f"📋 <b>الفاتورة:</b> <code>{invoice_id}</code>\n"
        f"📱 <b>رقم العميل:</b> {customer_phone or 'لم يُحدد بعد'}"
    )
    return notify_owner(message)


def notify_payment_pending(user_id, amount, order_id, payment_type='شحن رصيد', username=None, invoice_id=None, customer_phone=None):
    """إشعار بعملية دفع معلقة"""
    if payment_type == 'فاتورة تاجر':
        message = (
            f"⏳ <b>عملية دفع معلقة!</b>\n\n"
            f"📍 <b>النوع:</b> {payment_type}\n"
            f"👤 <b>التاجر:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"📋 <b>الفاتورة:</b> <code>{invoice_id or order_id}</code>\n"
            f"📱 <b>رقم العميل:</b> {customer_phone or 'غير محدد'}\n"
            f"🔗 <b>الطلب:</b> <code>{order_id}</code>"
        )
    else:
        message = (
            f"⏳ <b>عملية دفع معلقة!</b>\n\n"
            f"📍 <b>النوع:</b> {payment_type}\n"
            f"👤 <b>المستخدم:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"🔗 <b>الطلب:</b> <code>{order_id}</code>"
        )
    return notify_owner(message)


def notify_payment_success(user_id, amount, order_id, trans_id=None, payment_type='شحن رصيد', username=None, invoice_id=None, customer_phone=None, new_balance=None):
    """إشعار بنجاح عملية الدفع"""
    if payment_type == 'فاتورة تاجر':
        message = (
            f"🧾 <b>دفع فاتورة تاجر!</b>\n\n"
            f"👤 <b>التاجر:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"📋 <b>الفاتورة:</b> <code>{invoice_id or order_id}</code>\n"
            f"📱 <b>رقم العميل:</b> {customer_phone or 'غير محدد'}\n"
            f"🔗 <b>EdfaPay:</b> <code>{trans_id or 'N/A'}</code>"
        )
    else:
        message = (
            f"💳 <b>دفعة جديدة ناجحة!</b>\n\n"
            f"👤 <b>المستخدم:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"🔗 <b>الطلب:</b> <code>{order_id}</code>\n"
            f"🔗 <b>EdfaPay:</b> <code>{trans_id or 'N/A'}</code>"
        )
    
    if new_balance is not None:
        message += f"\n💵 <b>الرصيد الجديد:</b> {new_balance} ريال"
    
    return notify_owner(message)


def notify_payment_failed(user_id, amount, order_id, reason=None, payment_type='شحن رصيد', username=None, invoice_id=None, customer_phone=None):
    """إشعار بفشل عملية الدفع"""
    clean_reason = str(reason or 'غير محدد').replace('_', ' ').replace('*', '').replace('`', '')[:100]
    
    if payment_type == 'فاتورة تاجر':
        message = (
            f"❌ <b>فشل دفع فاتورة تاجر!</b>\n\n"
            f"👤 <b>التاجر:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"📋 <b>الفاتورة:</b> <code>{invoice_id or order_id}</code>\n"
            f"📱 <b>رقم العميل:</b> {customer_phone or 'غير محدد'}\n"
            f"❗ <b>السبب:</b> {clean_reason}"
        )
    else:
        message = (
            f"❌ <b>فشلت عملية الدفع!</b>\n\n"
            f"👤 <b>المستخدم:</b> {username or user_id}\n"
            f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
            f"💰 <b>المبلغ:</b> {amount} ريال\n"
            f"🔗 <b>الطلب:</b> <code>{order_id}</code>\n"
            f"❗ <b>السبب:</b> {clean_reason}"
        )
    return notify_owner(message)


def notify_recharge_request(user_id, amount, order_id, username=None):
    """إشعار بطلب شحن رصيد جديد (عند إنشاء الفاتورة)"""
    message = (
        f"🔔 <b>طلب شحن جديد!</b>\n\n"
        f"👤 <b>المستخدم:</b> {username or user_id}\n"
        f"🆔 <b>آيدي:</b> <code>{user_id}</code>\n"
        f"💰 <b>المبلغ:</b> {amount} ريال\n"
        f"📋 <b>رقم الطلب:</b> <code>{order_id}</code>\n\n"
        f"⏳ في انتظار الدفع..."
    )
    return notify_owner(message)
