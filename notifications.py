# -*- coding: utf-8 -*-
"""
نظام إشعارات المالك والمشرفين
يُستخدم لإرسال إشعارات تلقائية بجميع العمليات المهمة
"""

import logging
import threading
from extensions import bot, BOT_ACTIVE, ADMIN_ID, db

# استيراد معرف قناة التفاعلات
try:
    from config import ACTIVITY_CHANNEL_ID
except ImportError:
    ACTIVITY_CHANNEL_ID = ""

try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    USE_FIELD_FILTER = True
except ImportError:
    USE_FIELD_FILTER = False

logger = logging.getLogger(__name__)


# ==================== إرسال الإشعارات بالتوازي ====================

def send_message_async(chat_id, message, parse_mode='HTML'):
    """إرسال رسالة في thread منفصل (لا ينتظر)"""
    def send():
        try:
            if BOT_ACTIVE and bot:
                bot.send_message(chat_id, message, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"خطأ في إرسال رسالة لـ {chat_id}: {e}")
    
    threading.Thread(target=send, daemon=True).start()


def notify_owner_async(message, parse_mode='HTML'):
    """إرسال إشعار للمالك بدون انتظار (أسرع)"""
    if BOT_ACTIVE and bot and ADMIN_ID:
        send_message_async(ADMIN_ID, message, parse_mode)
        return True
    return False


def notify_multiple_async(recipients, message, parse_mode='HTML'):
    """
    إرسال رسالة لعدة مستلمين بالتوازي
    
    Args:
        recipients: قائمة من chat_ids
        message: نص الرسالة
        parse_mode: تنسيق الرسالة
    """
    def send_all():
        for chat_id in recipients:
            try:
                if BOT_ACTIVE and bot:
                    bot.send_message(chat_id, message, parse_mode=parse_mode)
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة لـ {chat_id}: {e}")
    
    threading.Thread(target=send_all, daemon=True).start()


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

def notify_new_charge(user_id, amount, method='edfapay', username=None, async_mode=True):
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
    
    # استخدام الوضع المتوازي للسرعة
    if async_mode:
        return notify_owner_async(message)
    return notify_owner(message)


def notify_withdrawal_request(user_id, amount, withdrawal_type, fee, net_amount, username=None, async_mode=True):
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
    
    if async_mode:
        return notify_owner_async(message)
    return notify_owner(message)


def notify_new_purchase(user_id, product_name, price, username=None, async_mode=True):
    """إشعار بعملية شراء جديدة"""
    message = (
        f"🛒 <b>عملية شراء جديدة!</b>\n\n"
        f"👤 <b>المشتري:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>المنتج:</b> {product_name}\n"
        f"💰 <b>السعر:</b> {price} ر.س"
    )
    
    if async_mode:
        return notify_owner_async(message)
    return notify_owner(message)


def notify_new_order(order_id, user_id, product_name, price, username=None, async_mode=True):
    """إشعار بطلب جديد (سلة)"""
    message = (
        f"📋 <b>طلب جديد!</b>\n\n"
        f"📄 <b>رقم الطلب:</b> <code>{order_id}</code>\n"
        f"👤 <b>العميل:</b> {username or user_id}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>المنتج:</b> {product_name}\n"
        f"💰 <b>المبلغ:</b> {price} ر.س"
    )
    
    if async_mode:
        return notify_owner_async(message)
    return notify_owner(message)


def notify_new_user(user_id, username=None, first_name=None, async_mode=True):
    """إشعار بتسجيل مستخدم جديد"""
    message = (
        f"👋 <b>مستخدم جديد!</b>\n\n"
        f"👤 <b>الاسم:</b> {first_name or 'غير محدد'}\n"
        f"📱 <b>Username:</b> @{username or 'غير محدد'}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>"
    )
    
    if async_mode:
        return notify_owner_async(message)
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


# ==================== قناة التفاعلات ====================

def send_activity_notification(activity_type, user_id, username=None, details=None):
    """
    إرسال إشعار للقناة عند حدوث تفاعل مهم
    
    Args:
        activity_type: نوع التفاعل (charge, withdraw, purchase, register)
        user_id: معرف المستخدم
        username: اسم المستخدم (اختياري)
        details: تفاصيل إضافية (dict)
    """
    try:
        if not ACTIVITY_CHANNEL_ID:
            return False
        
        channel_id = f"-100{ACTIVITY_CHANNEL_ID}" if not str(ACTIVITY_CHANNEL_ID).startswith('-') else ACTIVITY_CHANNEL_ID
        
        from datetime import datetime
        now = datetime.now().strftime('%Y/%m/%d - %H:%M:%S')
        
        # تحديد نوع النشاط والرسالة
        activity_icons = {
            'charge': '💰',
            'withdraw': '💸',
            'purchase': '🛒',
            'register': '👤',
            'login': '🔑'
        }
        
        activity_titles = {
            'charge': 'شحن رصيد',
            'withdraw': 'طلب سحب',
            'purchase': 'عملية شراء',
            'register': 'تسجيل جديد',
            'login': 'تسجيل دخول'
        }
        
        icon = activity_icons.get(activity_type, '📌')
        title = activity_titles.get(activity_type, 'تفاعل')
        
        # تنسيق اليوزرنيم
        username_display = f"@{username}" if username else "غير محدد"
        
        # بناء الرسالة
        message = f"{icon} <b>{title}</b>\n"
        message += f"━━━━━━━━━━━━━━━\n"
        message += f"👤 <b>المستخدم:</b> {username_display}\n"
        message += f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        
        # إضافة التفاصيل حسب النوع
        if details:
            if activity_type == 'charge' and 'amount' in details:
                message += f"💵 <b>المبلغ:</b> {details['amount']} ريال\n"
            elif activity_type == 'withdraw':
                if 'amount' in details:
                    message += f"💵 <b>المبلغ:</b> {details['amount']} ريال\n"
                if 'type' in details:
                    message += f"📋 <b>النوع:</b> {details['type']}\n"
            elif activity_type == 'purchase':
                if 'product' in details:
                    message += f"📦 <b>المنتج:</b> {details['product']}\n"
                if 'price' in details:
                    message += f"💵 <b>السعر:</b> {details['price']} ريال\n"
        
        message += f"━━━━━━━━━━━━━━━\n"
        message += f"🕐 <b>الوقت:</b> {now}"
        
        bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode='HTML'
        )
        logger.info(f"تم إرسال إشعار نشاط للقناة: {activity_type} - {user_id}")
        return True
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار النشاط: {e}")
        return False


# ==================== إرسال بيانات الطلب بالإيميل ====================

def send_order_email(to_email, order_items, total_price, new_balance=None):
    """
    إرسال بيانات الطلب عبر الإيميل للمشتري
    
    Args:
        to_email: إيميل المشتري
        order_items: قائمة المنتجات [{'name', 'price', 'order_id', 'hidden_data'(مفكوك), 'delivery_type'}]
        total_price: إجمالي السعر
        new_balance: الرصيد المتبقي (اختياري)
    """
    def _send():
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from config import SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD

            if not SMTP_EMAIL or not SMTP_PASSWORD or not to_email:
                return

            # بناء صفوف المنتجات
            items_html = ""
            for item in order_items:
                is_instant = item.get('delivery_type', 'instant') == 'instant'
                status_badge = (
                    '<span style="background:#00b894;color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">⚡ فوري</span>'
                    if is_instant else
                    '<span style="background:#fdcb6e;color:#333;padding:3px 10px;border-radius:12px;font-size:12px;">⏳ يدوي</span>'
                )

                hidden_section = ""
                if is_instant and item.get('hidden_data'):
                    hidden_section = f'''
                    <div style="background:#f0fff4;border:2px dashed #00b894;border-radius:10px;padding:14px;margin-top:10px;">
                        <div style="font-size:12px;color:#888;margin-bottom:6px;">🔐 بيانات الاشتراك:</div>
                        <div style="background:#1a1a2e;color:#55efc4;padding:12px;border-radius:8px;font-family:monospace;font-size:14px;white-space:pre-wrap;word-break:break-all;">{item["hidden_data"]}</div>
                    </div>'''
                elif not is_instant:
                    hidden_section = '''
                    <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:10px;padding:12px;margin-top:10px;text-align:center;">
                        <span style="font-size:13px;color:#f57f17;">⏳ سيتم تنفيذ طلبك قريباً</span>
                    </div>'''

                items_html += f'''
                <div style="background:#fafafa;border:1px solid #eee;border-radius:12px;padding:16px;margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <span style="font-size:15px;font-weight:700;">📦 {item["name"]}</span>
                        {status_badge}
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:13px;color:#666;">
                        <span>💰 {item["price"]:.2f} ر.س</span>
                        <span>🆔 #{item.get("order_id", "")}</span>
                    </div>
                    {hidden_section}
                </div>'''

            balance_section = ""
            if new_balance is not None:
                balance_section = f'''
                <div style="background:#f0f0ff;border-radius:10px;padding:14px;text-align:center;margin-top:16px;">
                    <span style="color:#888;font-size:13px;">💳 رصيدك المتبقي:</span>
                    <span style="font-size:20px;font-weight:800;color:#6c5ce7;margin-right:8px;">{new_balance:.2f} ر.س</span>
                </div>'''

            html = f"""
            <!DOCTYPE html>
            <html dir="rtl">
            <head><meta charset="UTF-8"></head>
            <body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Tahoma,sans-serif;">
                <div style="max-width:550px;margin:30px auto;background:#fff;border-radius:20px;box-shadow:0 10px 40px rgba(0,0,0,0.1);overflow:hidden;">
                    <div style="background:linear-gradient(135deg,#667eea,#764ba2);padding:30px;text-align:center;">
                        <h1 style="color:#fff;margin:0;font-size:26px;">🎉 تم الشراء بنجاح!</h1>
                        <p style="color:rgba(255,255,255,0.9);margin:8px 0 0;font-size:14px;">تفاصيل طلبك في TR Store</p>
                    </div>
                    <div style="padding:24px;">
                        {items_html}
                        <div style="background:linear-gradient(135deg,#667eea,#764ba2);border-radius:12px;padding:16px;text-align:center;margin-top:16px;">
                            <span style="color:rgba(255,255,255,0.8);font-size:13px;">الإجمالي</span><br>
                            <span style="color:#fff;font-size:24px;font-weight:800;">{total_price:.2f} ر.س</span>
                        </div>
                        {balance_section}
                    </div>
                    <div style="background:#f8f9fa;padding:16px;text-align:center;border-top:1px solid #eee;">
                        <p style="color:#aaa;font-size:11px;margin:0;">⚠️ احفظ هذا الإيميل — يحتوي على بيانات مشترياتك</p>
                        <p style="color:#ccc;font-size:11px;margin:6px 0 0;">TR Store © 2026</p>
                    </div>
                </div>
            </body>
            </html>"""

            msg = MIMEMultipart('alternative')
            msg['From'] = f"TR Store <{SMTP_EMAIL}>"
            msg['To'] = to_email
            msg['Subject'] = f"✅ تأكيد طلبك — {len(order_items)} منتج | TR Store"
            msg.attach(MIMEText("تم الشراء بنجاح! افتح الرسالة لعرض التفاصيل.", 'plain', 'utf-8'))
            msg.attach(MIMEText(html, 'html', 'utf-8'))

            try:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    logger.info(f"✅ تم إرسال إيميل الطلب إلى: {to_email}")
            except Exception:
                with smtplib.SMTP(SMTP_SERVER, 587, timeout=15) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    logger.info(f"✅ تم إرسال إيميل الطلب (TLS) إلى: {to_email}")
        except Exception as e:
            logger.error(f"⚠️ فشل إرسال إيميل الطلب إلى {to_email}: {e}")

    # إرسال في thread منفصل حتى لا يبطئ الاستجابة
    threading.Thread(target=_send, daemon=True).start()

