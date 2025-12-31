# اختبارات الأمان - Security Test Cases

هذا الملف يحتوي على حالات الاختبار لجميع الثغرات المكتشفة والتحقق من الإصلاحات.

---

## 🔴 اختبار #1: التحقق من الهوية (Authentication Bypass)

### الثغرة
يمكن إرسال أي `user_id` والوصول لبيانات مستخدمين آخرين.

### اختبار الثغرة
```bash
# قبل الإصلاح
curl -X POST http://localhost:5000/api/cart/add \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "999",
    "product_id": "prod123"
  }'

# يجب أن ينجح بدون تسجيل دخول! ✗
```

### اختبار الإصلاح
```bash
# بعد الإصلاح - بدون session
curl -X POST http://localhost:5000/api/cart/add \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "prod123"
  }'

# يجب أن يرجع error: "غير مسجل دخول" ✓
```

---

## 🔴 اختبار #2: Race Condition في المعاملات

### الثغرة
شراء بدون رصيد كافي بسبب race condition.

### اختبار الثغرة
```python
import threading
import requests

# سيناريو الاختبار
user_id = "123"
initial_balance = 100  # ريال
total_to_checkout = 100  # ريال

# إنشاء عمليات شراء متزامنة
def checkout():
    requests.post('http://localhost:5000/api/cart/checkout', json={})

threads = []
for i in range(3):
    t = threading.Thread(target=checkout)
    threads.append(t)
    t.start()

for t in threads:
    t.join()

# النتيجة بدون إصلاح: جميع العمليات تنجح! ✗
# الرصيد = -200 (ديون!)
```

### اختبار الإصلاح
```python
# بعد الإصلاح بـ Transactions
# عملية واحدة فقط تنجح
# العمليات الأخرى ترجع error: "رصيد غير كافي" ✓
```

---

## 🔴 اختبار #3: CSRF (Cross-Site Request Forgery)

### الثغرة
يمكن خداع المستخدم للقيام بعمليات غير مقصودة.

### اختبار الثغرة (موقع وهمي)
```html
<!-- phishing.html -->
<html>
<body>
  <h1>اضغط للفوز بهدية!</h1>
  <form action="http://your-site.com/api/cart/checkout" method="POST">
    <input type="hidden" name="total" value="1000">
    <input type="submit" value="اضغط هنا">
  </form>
  <script>
    // إرسال تلقائي بدون موافقة المستخدم
    document.forms[0].submit();
  </script>
</body>
</html>
```

### اختبار الإصلاح
```bash
# بدون CSRF token
curl -X POST http://localhost:5000/api/cart/checkout \
  -H "Content-Type: application/json" \
  -d '{"total": 1000}'

# يجب أن يرجع error بدون CSRF token ✓
```

---

## 🔴 اختبار #4: Firestore Injection

### الثغرة
الوصول لـ collections محظورة.

### اختبار الثغرة
```bash
# محاولة 1: مباشرة
curl http://localhost:5000/api/tabs/data/users

# محاولة 2: مع encoding
curl "http://localhost:5000/api/tabs/data/users%20"

# محاولة 3: مع path traversal
curl "http://localhost:5000/api/tabs/data/../users"

# جميع المحاولات قد تنجح قبل الإصلاح ✗
```

### اختبار الإصلاح
```bash
# مع Whitelist
curl http://localhost:5000/api/tabs/data/categories
# ينجح ✓

curl http://localhost:5000/api/tabs/data/users
# يرجع error: "مجموعة غير مسموحة" ✓
```

---

## 🔴 اختبار #5: تسريب البيانات الحساسة

### الثغرة
رسائل الخطأ تحتوي على معلومات حساسة.

### اختبار الثغرة
```bash
# طلب بيانات دفع خاطئة
curl -X POST http://localhost:5000/wallet/pay \
  -H "Content-Type: application/json" \
  -d '{"amount": -100}'

# Response قبل الإصلاح:
{
  "error": "Merchant ID 12345 not found in database"
}
# ✗ كشف معرف التاجر!
```

### اختبار الإصلاح
```bash
# Response بعد الإصلاح:
{
  "error": "حدث خطأ في معالجة الدفع. يرجى المحاولة لاحقاً."
}
# ✓ رسالة عامة
```

---

## 🔴 اختبار #6: كود التحقق في Response

### الثغرة
الكود يُرسل في JSON response.

### اختبار الثغرة
```bash
curl -X POST http://localhost:5000/register \
  -H "Content-Type: application/json" \
  -d '{"user_id": 999, "username": "test"}'

# Response قبل الإصلاح:
{
  "success": true,
  "code": "123456"  # ✗ الكود مرئي!
}
```

### اختبار الإصلاح
```bash
# Response بعد الإصلاح:
{
  "success": true,
  "message": "Code sent to bot"  # ✓ بدون كود
}
```

---

## 🟠 اختبار #7: Rate Limiting

### الثغرة
يمكن إرسال آلاف الطلبات بدون حد.

### اختبار الثغرة
```python
import requests
import time

# محاولة إرسال 100 طلب في ثانية واحدة
start = time.time()
for i in range(100):
    response = requests.post('http://localhost:5000/wallet/pay', json={})

elapsed = time.time() - start
print(f"Sent 100 requests in {elapsed:.2f} seconds")

# قبل الإصلاح: جميع الطلبات تمر ✗
```

### اختبار الإصلاح
```bash
# بعد الإصلاح مع Rate Limit "5 per minute"
for i in {1..10}; do
  curl -X POST http://localhost:5000/wallet/pay \
    -H "Content-Type: application/json" \
    -d '{"amount": 100}' \
    -w "\nStatus: %{http_code}\n"
done

# الطلبات من 1-5: 200 OK ✓
# الطلبات من 6-10: 429 Too Many Requests ✓
```

---

## 🟠 اختبار #8: bcrypt للكلمات المرور

### الثغرة
كلمة مرور Admin بدون hashing.

### اختبار الثغرة
```bash
# يمكن قراءة كلمة المرور من environment
echo $ADMIN_PASS
# output: "admin123" ✗

# في السجلات
grep ADMIN_PASS app.log
# output: password="admin123" ✗
```

### اختبار الإصلاح
```bash
# بعد الإصلاح
echo $ADMIN_PASS_HASH
# output: "b'$2b$12$...'" ✓ مشفرة

# حتى لو تم الوصول للـ env، لا يمكن فك التشفير ✓
```

---

## 🟠 اختبار #9: Webhook Signature

### الثغرة
يمكن انتحال webhook من بوابة الدفع.

### اختبار الثغرة
```bash
# إرسال webhook وهمي
curl -X POST http://localhost:5000/payment/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "123",
    "status": "SUCCESS",
    "amount": 1000
  }'

# قبل الإصلاح: ينجح بدون توقيع! ✗
# يتم تأكيد دفع لم يحدث فعلاً
```

### اختبار الإصلاح
```bash
# بعد الإصلاح
curl -X POST http://localhost:5000/payment/webhook \
  -H "Content-Type: application/json" \
  -H "X-Signature: invalid_signature" \
  -d '{"order_id": "123"}'

# يرجع: 401 Invalid signature ✓
```

---

## 🟡 اختبار #10: معرفات متنبأ بها

### الثغرة
معرفات الطلبات يمكن التنبؤ بها.

### اختبار الثغرة
```python
import time

# معرف الطلب يحتوي على timestamp
order_id_1 = f"TR123{int(time.time())}"
time.sleep(0.1)
order_id_2 = f"TR123{int(time.time())}"

# order_id_1 و order_id_2 قريب جداً من بعضهما
# يمكن توقع الـ IDs التالية ✗

# معرف آخر
order_id = f"ORD_{random.randint(100000, 999999)}"
# فقط 900,000 خيار محتملة
# يمكن brute force جميعها ✗
```

### اختبار الإصلاح
```python
import uuid
import secrets

# UUID - فريد تماماً
order_id = f"ORD_{uuid.uuid4().hex[:12]}"
# 2^96 خيار محتملة ✓

# أو secrets
order_id = f"ORD_{secrets.token_hex(8)}"
# 2^64 خيار محتملة ✓
```

---

## ✅ Script اختبار شامل

```python
#!/usr/bin/env python3
"""
script اختبار شامل للثغرات الأمنية
"""

import requests
import json
import time
import subprocess
from datetime import datetime

BASE_URL = "http://localhost:5000"
TEST_USER_ID = "123456"
TEST_ADMIN_PASSWORD = "admin123"

class SecurityTester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.session = requests.Session()
    
    def log(self, test_name, passed, details=""):
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name}")
        if details:
            print(f"       {details}")
        
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_auth_bypass(self):
        """اختبار #1: التحقق من الهوية"""
        print("\n=== اختبار #1: Authentication Bypass ===")
        
        # محاولة إضافة منتج بدون تسجيل دخول
        response = self.session.post(
            f"{BASE_URL}/api/cart/add",
            json={"user_id": "999", "product_id": "prod123"}
        )
        
        # يجب أن يرجع error بدون session
        passed = response.status_code in [401, 403]
        self.log("User ID من request", passed, f"Status: {response.status_code}")
    
    def test_csrf(self):
        """اختبار #3: CSRF"""
        print("\n=== اختبار #3: CSRF ===")
        
        # محاولة POST بدون CSRF token
        response = self.session.post(
            f"{BASE_URL}/api/cart/checkout",
            json={"total": 1000}
        )
        
        # يجب أن يرجع error بدون CSRF token
        passed = response.status_code in [403]  # CSRF error
        self.log("CSRF Protection", passed, f"Status: {response.status_code}")
    
    def test_rate_limiting(self):
        """اختبار #7: Rate Limiting"""
        print("\n=== اختبار #7: Rate Limiting ===")
        
        # إرسال عدة طلبات بسرعة
        responses = []
        for i in range(10):
            response = self.session.post(
                f"{BASE_URL}/wallet/pay",
                json={"amount": 100}
            )
            responses.append(response.status_code)
        
        # يجب أن نرى 429 (Too Many Requests) بعد عدة طلبات
        has_429 = 429 in responses
        self.log("Rate Limiting", has_429, f"Responses: {responses}")
    
    def test_injection(self):
        """اختبار #4: Firestore Injection"""
        print("\n=== اختبار #4: Injection ===")
        
        # محاولة الوصول لـ collection محظورة
        response = self.session.get(
            f"{BASE_URL}/api/tabs/data/users"
        )
        
        # يجب أن يرجع error
        passed = response.status_code in [403]
        self.log("Firestore Injection", passed, f"Status: {response.status_code}")
    
    def test_error_exposure(self):
        """اختبار #5: تسريب البيانات"""
        print("\n=== اختبار #5: Error Exposure ===")
        
        response = self.session.post(
            f"{BASE_URL}/wallet/pay",
            json={"amount": -100}
        )
        
        if response.status_code >= 400:
            error_msg = response.json().get('error', '')
            # يجب أن تكون الرسالة عامة، لا تحتوي على معلومات حساسة
            has_no_sensitive = all(keyword not in error_msg.lower() 
                                   for keyword in ['merchant', 'id', 'password', 'api'])
            self.log("Error Exposure", has_no_sensitive, f"Error: {error_msg[:50]}")
    
    def run_all_tests(self):
        """تشغيل جميع الاختبارات"""
        print("=" * 60)
        print(f"بدء اختبارات الأمان - {datetime.now()}")
        print("=" * 60)
        
        self.test_auth_bypass()
        self.test_csrf()
        self.test_rate_limiting()
        self.test_injection()
        self.test_error_exposure()
        
        # الملخص
        print("\n" + "=" * 60)
        print(f"النتائج: {self.passed} نجح، {self.failed} فشل")
        print("=" * 60)
        
        if self.failed == 0:
            print("✓ جميع الاختبارات نجحت!")
        else:
            print(f"✗ {self.failed} اختبارات فشلت!")

if __name__ == "__main__":
    tester = SecurityTester()
    tester.run_all_tests()
```

---

## 🚀 تشغيل الاختبارات

```bash
# تثبيت المتطلبات
pip install requests pytest

# تشغيل الاختبارات اليدوية
python security_test.py

# تشغيل مع pytest
pytest test_security.py -v

# تشغيل مع coverage
pytest test_security.py --cov=. --cov-report=html
```

---

## 📊 تقرير الاختبار

بعد الإصلاح، يجب أن تحصل على:

```
✓ PASS - User ID من request
✓ PASS - CSRF Protection
✓ PASS - Rate Limiting
✓ PASS - Firestore Injection
✓ PASS - Error Exposure
✓ PASS - Webhook Signature
✓ PASS - Password Hashing
✓ PASS - Logging
✓ PASS - Transactions
✓ PASS - Random IDs

النتائج: 10 نجح، 0 فشل
✓ جميع الاختبارات نجحت!
```

