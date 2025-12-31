# دليل الإصلاح السريع (Quick Fix Guide)

هذا الملف يحتوي على أكواد الإصلاح الجاهزة للنسخ والاستخدام مباشرة.

---

## ✅ الإصلاح #1: استخدام Session بدلاً من Request Data

### المشكلة
```python
# ❌ غير آمن
user_id = str(data.get('user_id'))
```

### الحل
```python
# ✅ آمن
user_id = session.get('user_id')
if not user_id:
    return jsonify({'error': 'غير مسجل دخول'}), 401

user_id = str(user_id)
```

### الملفات التي تحتاج تعديل
- `routes/cart.py` - سطور: 46, 115
- `routes/wallet.py` - السطور التي تستخدم `data.get('user_id')`
- `services/payment_methods_service.py` - سطر 56

---

## ✅ الإصلاح #2: استخدام Transactions للعمليات المالية

### المشكلة
```python
# ❌ غير آمن - race condition
balance = get_balance(user_id)
if balance < total:
    return error
new_balance = balance - total
db.update({'balance': new_balance})
```

### الحل
```python
# ✅ آمن
from google.cloud.firestore import transactional

@transactional
def checkout_atomic(transaction, user_ref, total):
    user_doc = transaction.get(user_ref)
    balance = float(user_doc.get('balance', 0))
    
    if balance < total:
        raise ValueError('رصيد غير كافي')
    
    transaction.update(user_ref, {
        'balance': balance - total,
        'last_transaction': firestore.SERVER_TIMESTAMP
    })
    
    return True

# الاستخدام
try:
    transaction = db.transaction()
    transaction(checkout_atomic, user_ref, total)
except ValueError as e:
    return {'error': str(e)}
```

### الملفات التي تحتاج تعديل
- `routes/cart.py` - دالة `api_cart_checkout` (سطور 219-350)
- `routes/wallet.py` - دالة `wallet_pay` (سطور 75-170)

---

## ✅ الإصلاح #3: إضافة CSRF Protection

### المرحلة 1: تثبيت المكتبة
```bash
pip install flask-wtf
```

### المرحلة 2: إضافة CSRF للتطبيق
```python
# في [app.py] أضف:
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)
```

### المرحلة 3: حماية API Routes
```python
# في [routes/cart.py]:
from flask_wtf.csrf import csrf_exempt

@cart_bp.route('/api/cart/checkout', methods=['POST'])
@csrf.protect  # أضف هذا
def api_cart_checkout():
    # ...

# للـ API endpoints التي لا تحتاج CSRF (مثل external APIs):
@cart_bp.route('/webhook/payment', methods=['POST'])
@csrf_exempt
def payment_webhook():
    # ...
```

### المرحلة 4: إضافة CSRF Token في HTML Forms
```html
<!-- في templates يجب أن يكون لديك: -->
<form method="POST">
    {{ csrf_token() }}
    <!-- بقية الـ form -->
</form>
```

---

## ✅ الإصلاح #4: استخدام Whitelist بدلاً من Blacklist

### المشكلة
```python
# ❌ غير آمن - سهل الالتفاف
exclude = ['users', 'charge_keys', 'pending_payments']
if collection_name in exclude:
    return error
data = get_collection_data(collection_name)
```

### الحل
```python
# ✅ آمن - whitelist
ALLOWED_COLLECTIONS = [
    'categories',
    'products',
    'merchants',
    'promotions',
    'reviews'
]

if collection_name not in ALLOWED_COLLECTIONS:
    return jsonify({
        'status': 'error',
        'message': 'مجموعة غير مسموحة'
    }), 403

data = get_collection_data(collection_name, limit=limit)
```

### الملفات التي تحتاج تعديل
- `routes/api_routes.py` - دالة `get_tab_data` (سطور 40-65)

---

## ✅ الإصلاح #5: إخفاء رسائل الخطأ الحقيقية

### المشكلة
```python
# ❌ تسريب بيانات
try:
    response = requests.post(EDFAPAY_API_URL, data=payload)
    result = response.json()
except Exception as e:
    return {'error': str(e)}  # ✗ تسريب معلومات حساسة
```

### الحل
```python
# ✅ آمن
import logging

logger = logging.getLogger('security')

try:
    response = requests.post(EDFAPAY_API_URL, data=payload, timeout=30)
    result = response.json()
    
    if response.status_code == 200 and result.get('redirect_url'):
        return {'success': True, 'payment_url': result['redirect_url']}
    else:
        logger.error(f"Payment failed: {result}")
        return {
            'success': False,
            'message': 'حدث خطأ في معالجة الدفع. يرجى المحاولة لاحقاً.'
        }
        
except requests.exceptions.Timeout:
    logger.error("Payment gateway timeout")
    return {'success': False, 'message': 'انتهت مهلة الاتصال. حاول مرة أخرى.'}
    
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    return {'success': False, 'message': 'حدث خطأ غير متوقع.'}
```

### الملفات التي تحتاج تعديل
- `payment.py` - دالة `create_edfapay_invoice` (سطور 85-91)
- `payment.py` - دالة `create_wallet_payment` (سطور 139-145)
- `routes/wallet.py` - دالة `wallet_pay` (سطور 142-160)
- `routes/payment_routes.py` - دالة `payment_success` (سطور 165-185)

---

## ✅ الإصلاح #6: إضافة Rate Limiting على Endpoints الحساسة

### المشكلة
```python
# ❌ بدون rate limiting
@wallet_bp.route('/wallet/pay', methods=['POST'])
def wallet_pay():
    # يمكن لمهاجم إرسال آلاف الطلبات
```

### الحل
```python
# ✅ مع rate limiting

# في [app.py] لديك بالفعل:
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=RATE_LIMIT_DEFAULT,
)

# أضف rate limits محددة على endpoints الحساسة:
@wallet_bp.route('/wallet/pay', methods=['POST'])
@limiter.limit("5 per minute")  # 5 طلبات فقط في الدقيقة
def wallet_pay():
    # ...

@auth_bp.route('/verify-code', methods=['POST'])
@limiter.limit("3 per minute")  # 3 محاولات تحقق فقط
def verify_code_api():
    # ...

@cart_bp.route('/api/cart/checkout', methods=['POST'])
@limiter.limit("10 per hour")  # 10 عمليات شراء في الساعة
def api_cart_checkout():
    # ...

@routes/admin.py
@admin_bp.route('/api/admin/send_code', methods=['POST'])
@limiter.limit("5 per hour")  # محاولات محدودة للدخول
def api_send_admin_code():
    # ...
```

---

## ✅ الإصلاح #7: استخدام bcrypt لكلمات المرور

### المرحلة 1: تثبيت المكتبة
```bash
pip install bcrypt
```

### المرحلة 2: إنشاء Hash الكلمة
```python
import bcrypt
import os

# أثناء الإعداد الأول (مرة واحدة):
admin_password = "your_secure_password_here"
salt = bcrypt.gensalt(rounds=12)
password_hash = bcrypt.hashpw(admin_password.encode(), salt)

# احفظ هذا في متغير البيئة:
# ADMIN_PASS_HASH=b'$2b$12$...'
print(f"ADMIN_PASS_HASH={password_hash.hex()}")
```

### المرحلة 3: التحقق من الكلمة
```python
# في [routes/admin.py] استبدل:
# من:
admin_password = os.environ.get('ADMIN_PASS', 'admin123')
if password != admin_password:
    return error

# إلى:
import bcrypt

def verify_admin_password(submitted_password):
    admin_pass_hash = os.environ.get('ADMIN_PASS_HASH', '')
    if not admin_pass_hash:
        logger.error("ADMIN_PASS_HASH not configured")
        return False
    
    try:
        return bcrypt.checkpw(
            submitted_password.encode(),
            bytes.fromhex(admin_pass_hash)
        )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

# في api_send_admin_code:
if not verify_admin_password(password):
    # سجل المحاولة الفاشلة
    failed_login_attempts[client_ip]['count'] += 1
    return error
```

---

## ✅ الإصلاح #8: إضافة Logging للعمليات الحساسة

### المرحلة 1: إعداد Logger
```python
# أضف في [app.py]:
import logging
from logging.handlers import RotatingFileHandler

# إنشاء logger للأمان
security_logger = logging.getLogger('security')
security_handler = RotatingFileHandler(
    'security.log',
    maxBytes=10485760,  # 10MB
    backupCount=10
)
security_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
security_handler.setFormatter(security_formatter)
security_logger.addHandler(security_handler)
security_logger.setLevel(logging.INFO)
```

### المرحلة 2: تسجيل العمليات الحساسة
```python
# في [routes/cart.py]:
from app import security_logger

@cart_bp.route('/api/cart/checkout', methods=['POST'])
def api_cart_checkout():
    user_id = session.get('user_id')
    
    security_logger.info(
        f"Checkout started | user={user_id} | ip={request.remote_addr} | time={datetime.now()}"
    )
    
    # ... عملية الشراء ...
    
    security_logger.info(
        f"Checkout completed | user={user_id} | total={total} | items={len(available_items)}"
    )

# في [routes/wallet.py]:
@wallet_bp.route('/wallet/pay', methods=['POST'])
def wallet_pay():
    user_id = session.get('user_id')
    amount = data.get('amount')
    
    security_logger.info(
        f"Payment initiated | user={user_id} | amount={amount} | ip={request.remote_addr}"
    )
    
    # ... معالجة الدفع ...

# في [routes/admin.py]:
@admin_bp.route('/api/admin/send_code', methods=['POST'])
def api_send_admin_code():
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    security_logger.warning(
        f"Admin login attempt | ip={client_ip} | time={datetime.now()}"
    )
```

---

## ✅ الإصلاح #9: التحقق من صحة Webhook من بوابة الدفع

### الحل
```python
# في [payment.py] أضف:
import hmac
import hashlib

def verify_payment_webhook(data, signature, secret_key):
    """التحقق من توقيع webhook من بوابة الدفع"""
    # ترتيب المفاتيح وإنشاء الرسالة
    sorted_data = json.dumps(data, sort_keys=True, separators=(',', ':'))
    
    # حساب التوقيع المتوقع
    expected_signature = hmac.new(
        secret_key.encode(),
        sorted_data.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # مقارنة آمنة ضد timing attacks
    return hmac.compare_digest(signature, expected_signature)

# في [routes/payment_routes.py]:
@payment_bp.route('/payment/webhook', methods=['POST'])
@csrf_exempt  # webhooks لا تحتاج CSRF
def payment_webhook():
    data = request.json or {}
    signature = request.headers.get('X-Signature', '')
    
    webhook_secret = os.environ.get('WEBHOOK_SECRET', '')
    
    if not verify_payment_webhook(data, signature, webhook_secret):
        security_logger.warning(
            f"Invalid webhook signature | ip={request.remote_addr}"
        )
        return {'error': 'Invalid signature'}, 401
    
    # معالجة الـ webhook الموثوق
    order_id = data.get('order_id')
    status = data.get('status')
    
    security_logger.info(
        f"Valid webhook received | order={order_id} | status={status}"
    )
    
    # تحديث حالة الطلب
    # ...
```

---

## ✅ الإصلاح #10: استخدام معرفات عشوائية آمنة

### المشكلة
```python
# ❌ غير آمن - يمكن التنبؤ
order_id = f"TR{user_id}{int(time.time())}"
order_id = f"ORD_{random.randint(100000, 999999)}"
```

### الحل
```python
# ✅ آمن - عشوائي تماماً
import uuid
import secrets

# الخيار 1: استخدام UUID
order_id = f"ORD_{uuid.uuid4().hex[:12]}"

# الخيار 2: استخدام secrets (أفضل للـ tokens)
order_id = f"ORD_{secrets.token_hex(8)}"

# الخيار 3: UUID مع timestamp
order_id = f"ORD_{int(time.time())}_{uuid.uuid4().hex[:8]}"
```

### الملفات التي تحتاج تعديل
- `routes/cart.py` - سطر 302
- `routes/wallet.py` - سطر 111
- `payment.py` - دالة `create_edfapay_invoice`

---

## 📋 جدول الأولويات

| الأولوية | الإصلاح | الملفات | الوقت المتوقع |
|---------|--------|---------|---------------|
| 1 | Session بدلاً من request data | cart.py, wallet.py | 30 دقيقة |
| 2 | Transactions للعمليات المالية | cart.py, wallet.py | 1 ساعة |
| 3 | CSRF Protection | app.py, templates | 45 دقيقة |
| 4 | Whitelist للـ collections | api_routes.py | 15 دقيقة |
| 5 | إخفاء رسائل الخطأ | payment.py, routes | 1 ساعة |
| 6 | Rate Limiting | routes | 45 دقيقة |
| 7 | bcrypt للكلمات المرور | admin.py | 1 ساعة |
| 8 | Logging للعمليات | جميع routes | 1 ساعة |
| 9 | Webhook Signature Verification | payment_routes.py | 1 ساعة |
| 10 | عشوائية آمنة | cart.py, wallet.py | 30 دقيقة |

**الإجمالي المتوقع:** 8-9 ساعات

---

## 🧪 اختبار الإصلاحات

```bash
# تثبيت الأدوات المطلوبة
pip install pytest flask-testing bandit

# اختبار الأمان
bandit -r . --exclude venv

# اختبارات الوحدة
pytest tests/

# اختبارات التكامل
pytest tests/integration/

# اختبار الأداء
locust -f locustfile.py
```

---

## ✅ Checklist ما بعد الإصلاح

- [ ] اختبر جميع endpoints
- [ ] تحقق من Logs بحثاً عن أخطاء
- [ ] اختبر في بيئة محلية قبل الإنتاج
- [ ] قم بـ backup قاعدة البيانات
- [ ] أعد الخدمة تدريجياً
- [ ] راقب الـ errors الجديدة
- [ ] اطلب من مختبر أمان خارجي مراجعة الكود

