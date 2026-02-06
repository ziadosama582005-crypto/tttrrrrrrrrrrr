# 📧 نظام تسجيل الدخول بالإيميل - التوثيق الكامل

## نظرة عامة

نظام يسمح للمستخدمين بتسجيل الدخول باستخدام بريدهم الإلكتروني بدلاً من Telegram.
يتم إرسال كود تحقق مكون من 6 أرقام إلى البريد الإلكتروني.

**التدفق:**
```
المستخدم يدخل الإيميل → النظام يبحث في Firebase → يولّد كود 6 أرقام 
→ يرسله للإيميل → المستخدم يدخل الكود → تسجيل دخول ناجح
```

---

## 🛠️ خطوات التركيب من الصفر

### الخطوة 1: إضافة إعدادات SMTP في config.py

**الملف:** `config.py`
**المكان:** أضف في نهاية الملف (بعد إعدادات Tabby)

```python
# === إعدادات البريد الإلكتروني (SMTP) ===
# يمكن تغييرها من Render Environment Variables
SMTP_SERVER = os.environ.get("SMTP_SERVER", "mail.privateemail.com")  # Namecheap افتراضي
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))  # منفذ SSL
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")  # الإيميل
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # كلمة المرور
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "TR Store")  # اسم المرسل
```

---

### الخطوة 2: إضافة imports في routes/auth_routes.py

**الملف:** `routes/auth_routes.py`
**المكان:** في أعلى الملف مع باقي الـ imports

```python
# أضف هذه في أعلى الملف
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD
```

---

### الخطوة 3: إضافة دالة إرسال الإيميل

**الملف:** `routes/auth_routes.py`
**المكان:** أضف قبل الـ routes (قبل @auth_bp.route)

```python
# ==================== نظام تسجيل الدخول بالإيميل ====================

def send_email_otp(to_email, code):
    """إرسال كود التحقق عبر الإيميل"""
    try:
        if not SMTP_EMAIL or not SMTP_PASSWORD:
            print("❌ إعدادات SMTP غير مكتملة")
            return False
            
        msg = MIMEMultipart('alternative')
        msg['From'] = f"TR Store <{SMTP_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = "🔐 كود الدخول - TR Store"

        # تصميم الرسالة HTML
        html_body = f"""
        <!DOCTYPE html>
        <html dir="rtl">
        <head><meta charset="UTF-8"></head>
        <body style="margin: 0; padding: 0; background-color: #f0f2f5; font-family: 'Segoe UI', Tahoma, sans-serif;">
            <div style="max-width: 500px; margin: 30px auto; background: white; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.1); overflow: hidden;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🔐 TR Store</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">رمز التحقق الخاص بك</p>
                </div>
                <div style="padding: 40px 30px; text-align: center;">
                    <p style="color: #666; font-size: 16px; margin-bottom: 30px;">مرحباً! 👋<br>استخدم الرمز التالي لتسجيل الدخول:</p>
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px; border-radius: 15px; display: inline-block;">
                        <span style="font-size: 36px; font-weight: bold; color: white; letter-spacing: 8px;">{code}</span>
                    </div>
                    <p style="color: #999; font-size: 14px; margin-top: 30px;">⏰ هذا الرمز صالح لمدة <strong>10 دقائق</strong> فقط</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                    <p style="color: #aaa; font-size: 12px;">⚠️ إذا لم تطلب هذا الرمز، تجاهل هذا الإيميل</p>
                </div>
                <div style="background: #f8f9fa; padding: 20px; text-align: center;">
                    <p style="color: #888; font-size: 12px; margin: 0;">TR Store © 2024</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(f"رمز التحقق: {code}", 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        print(f"📧 محاولة إرسال إيميل إلى: {to_email} عبر {SMTP_SERVER}:{SMTP_PORT}")
        
        # محاولة SSL أولاً (port 465)
        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
                print(f"✅ تم إرسال الإيميل بنجاح إلى: {to_email}")
                return True
        except Exception as ssl_error:
            print(f"⚠️ فشل SSL: {ssl_error}, جاري تجربة TLS...")
            
        # محاولة TLS كخيار ثاني (port 587)
        try:
            with smtplib.SMTP(SMTP_SERVER, 587, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
                print(f"✅ تم إرسال الإيميل بنجاح (TLS) إلى: {to_email}")
                return True
        except Exception as tls_error:
            print(f"❌ فشل TLS أيضاً: {tls_error}")
            return False
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ خطأ في المصادقة: {e}")
        return False
    except Exception as e:
        print(f"❌ خطأ في إرسال الإيميل: {e}")
        return False
```

---

### الخطوة 4: إضافة Endpoint إرسال الكود

**الملف:** `routes/auth_routes.py`
**المكان:** أضف بعد دالة send_email_otp

```python
@auth_bp.route('/api/auth/send-code', methods=['POST'])
def send_code_email():
    """إرسال كود التحقق للإيميل"""
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})
        
    email = data.get('email', '').strip().lower()
    
    if not email or '@' not in email:
        return jsonify({'success': False, 'message': 'الرجاء إدخال بريد إلكتروني صحيح'})

    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        results = list(query.stream())

        if results:
            user_doc = results[0]
            user_id = user_doc.id
            user_ref = users_ref.document(user_id)
            print(f"✅ تم العثور على المستخدم: {user_id}")
        else:
            return jsonify({'success': False, 'message': 'لا يوجد حساب مرتبط بهذا البريد الإلكتروني'})

        # توليد وحفظ الكود
        new_code = generate_code()
        user_ref.update({
            'verification_code': new_code,
            'code_time': time.time()
        })
        
        # إرسال الإيميل
        if send_email_otp(email, new_code):
            return jsonify({'success': True, 'message': f'✅ تم إرسال الرمز إلى {email}', 'email': email})
        else:
            # إذا فشل الإيميل، نحاول إرسال عبر Telegram
            try:
                user_data = user_doc.to_dict()
                message_text = f"📧 كود التحقق للدخول:\n\n<code>{new_code}</code>\n\n⏰ صالح لمدة 10 دقائق"
                bot.send_message(int(user_id), message_text, parse_mode='HTML')
                return jsonify({'success': True, 'message': '✅ تم إرسال الرمز عبر Telegram', 'email': email})
            except:
                return jsonify({'success': False, 'message': 'فشل الإرسال!'})

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ في النظام'})
```

---

### الخطوة 5: إضافة Endpoint تسجيل الدخول

**الملف:** `routes/auth_routes.py`
**المكان:** أضف بعد send_code_email

```python
@auth_bp.route('/api/auth/login', methods=['POST'])
def login_email():
    """التحقق من الكود وتسجيل الدخول بالإيميل"""
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'بيانات غير صالحة'})
        
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    
    if not email or not code:
        return jsonify({'success': False, 'message': 'الرجاء إدخال البريد والكود'})
    
    try:
        query = db.collection('users').where('email', '==', email).limit(1)
        results = list(query.stream())
        
        if not results:
            return jsonify({'success': False, 'message': 'الحساب غير موجود'})
            
        user_doc = results[0]
        user_data = user_doc.to_dict()
        
        # التحقق من انتهاء صلاحية الكود (10 دقائق)
        code_time = user_data.get('code_time', 0)
        if time.time() - code_time > 600:
            return jsonify({'success': False, 'message': 'انتهت صلاحية الكود، اطلب كود جديد'})
        
        # التحقق من الكود
        saved_code = str(user_data.get('verification_code', ''))
        if saved_code == code:
            # تجديد الجلسة للأمان
            regenerate_session()
            
            # دخول ناجح
            session['user_id'] = user_doc.id
            session['user_name'] = user_data.get('username', user_data.get('first_name', 'مستخدم'))
            session['user_email'] = email
            session['logged_in'] = True
            session['login_time'] = time.time()  # ⚠️ مهم جداً لمنع انتهاء الجلسة فوراً!
            session.permanent = True
            session.modified = True
            
            # مسح الكود بعد الاستخدام
            db.collection('users').document(user_doc.id).update({
                'verification_code': None,
                'code_time': None
            })
            
            print(f"✅ تم تسجيل دخول المستخدم: {user_doc.id}")
            return jsonify({'success': True, 'message': 'تم تسجيل الدخول بنجاح'})
        else:
            return jsonify({'success': False, 'message': 'الكود غير صحيح'})
            
    except Exception as e:
        print(f"❌ Login Error: {e}")
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء الدخول'})
```

---

### الخطوة 6: إضافة واجهة المستخدم (HTML + JavaScript)

**الملف:** `templates/categories.html` (أو أي صفحة تسجيل دخول)
**المكان:** داخل modal أو form تسجيل الدخول

#### HTML:
```html
<!-- نموذج إدخال الإيميل -->
<div id="step1" class="step active">
    <form id="emailForm">
        <input type="email" id="loginEmail" placeholder="example@gmail.com" required>
        <button type="submit">إرسال كود التحقق</button>
    </form>
    <div id="emailError" class="error-msg"></div>
</div>

<!-- نموذج إدخال الكود -->
<div id="step2" class="step">
    <form id="verifyForm">
        <input type="text" id="verifyCode" placeholder="أدخل الكود" maxlength="6" required>
        <button type="submit">تأكيد الدخول</button>
    </form>
    <div id="codeError" class="error-msg"></div>
</div>
```

#### JavaScript:
```javascript
// متغير لحفظ الإيميل
window.loginEmail = null;

// إرسال كود التحقق
document.getElementById('emailForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value.trim();
    const errorDiv = document.getElementById('emailError');
    
    try {
        const response = await fetch('/api/auth/send-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email })
        });
        const data = await response.json();
        
        if (data.success) {
            window.loginEmail = email;  // حفظ الإيميل للخطوة التالية
            document.getElementById('step1').classList.remove('active');
            document.getElementById('step2').classList.add('active');
            document.getElementById('verifyCode').focus();
        } else {
            errorDiv.textContent = data.message;
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        errorDiv.textContent = 'خطأ في الاتصال بالسيرفر';
        errorDiv.style.display = 'block';
    }
});

// التحقق من الكود
document.getElementById('verifyForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const code = document.getElementById('verifyCode').value.trim();
    const errorDiv = document.getElementById('codeError');
    
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                email: window.loginEmail,
                code: code 
            })
        });
        const data = await response.json();
        
        if (data.success) {
            window.loginEmail = null;
            location.reload();  // إعادة تحميل الصفحة
        } else {
            errorDiv.textContent = data.message;
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        errorDiv.textContent = 'خطأ في الاتصال بالسيرفر';
        errorDiv.style.display = 'block';
    }
});
```

---

### الخطوة 7: إعداد Render Environment Variables

اذهب إلى **Render Dashboard** → **Environment** وأضف:

| المتغير | الوصف | مثال |
|---------|-------|------|
| `SMTP_SERVER` | سيرفر البريد | `mail.privateemail.com` |
| `SMTP_PORT` | المنفذ (465 لـ SSL، 587 لـ TLS) | `465` |
| `SMTP_EMAIL` | إيميل المرسل | `tr@gamerstr1.com` |
| `SMTP_PASSWORD` | كلمة المرور | `yourpassword123` |
| `SMTP_FROM_NAME` | اسم المرسل (اختياري) | `TR Store` |

**ملاحظة:** `SMTP_FROM_NAME` اختياري، القيمة الافتراضية `TR Store`

---

### الخطوة 8: إعداد Firebase

1. اذهب إلى **Firebase Console** → **Firestore Database**
2. افتح collection **users**
3. لكل مستخدم، أضف حقل **email**:

```javascript
// Firebase > Firestore > users > {user_id}
{
    "username": "اسم_المستخدم",
    "email": "user@example.com",      // ← أضف هذا الحقل
    "balance": 0.0
}
```

---

## 📁 ملخص الملفات والأماكن

| الملف | ما يجب إضافته | المكان |
|-------|---------------|--------|
| `config.py` | إعدادات SMTP | نهاية الملف |
| `routes/auth_routes.py` | imports | أعلى الملف (سطر 1-15) |
| `routes/auth_routes.py` | دالة `send_email_otp` | قبل الـ routes |
| `routes/auth_routes.py` | `/api/auth/send-code` | بعد الدالة |
| `routes/auth_routes.py` | `/api/auth/login` | بعد send-code |
| `templates/*.html` | HTML + JavaScript | في modal تسجيل الدخول |

---

## � API Endpoints

### إرسال كود التحقق
```
POST /api/auth/send-code
Content-Type: application/json

Request:
{
    "email": "user@example.com"
}

Response (نجاح):
{
    "success": true,
    "message": "✅ تم إرسال الرمز إلى user@example.com",
    "email": "user@example.com"
}

Response (فشل):
{
    "success": false,
    "message": "لا يوجد حساب مرتبط بهذا البريد الإلكتروني"
}
```

### تسجيل الدخول بالكود
```
POST /api/auth/login
Content-Type: application/json

Request:
{
    "email": "user@example.com",
    "code": "123456"
}

Response (نجاح):
{
    "success": true,
    "message": "تم تسجيل الدخول بنجاح"
}

Response (فشل):
{
    "success": false,
    "message": "الكود غير صحيح"
}
```

### إرسال كود بالإيميل (البديل في app.py)

**الملف:** `app.py`
**الميزات الإضافية:**
- Rate Limiting: 3 طلبات/دقيقة
- حفظ الكود في الذاكرة + Firebase
- استخدام `email_service.py`
- Fallback تلقائي لـ Telegram

```
POST /api/send_code_by_email
Content-Type: application/json

Request:
{
    "email": "user@example.com"
}

Response (نجاح - إيميل):
{
    "success": true,
    "message": "✅ تم إرسال كود التحقق إلى user@example.com",
    "user_id": "123456789",
    "method": "email"
}

Response (نجاح - Telegram كبديل):
{
    "success": true,
    "message": "✅ تم إرسال الكود عبر Telegram (خدمة الإيميل غير متاحة)",
    "user_id": "123456789",
    "method": "telegram"
}

Response (فشل):
{
    "success": false,
    "message": "لا يوجد حساب مرتبط بهذا البريد الإلكتروني"
}
```

### مقارنة بين الـ Endpoints

| الميزة | `/api/auth/send-code` | `/api/send_code_by_email` |
|--------|----------------------|---------------------------|
| **الملف** | auth_routes.py | app.py |
| **Rate Limiting** | يدوي (5 محاولات) | `@limiter` (3/دقيقة) |
| **حفظ الكود** | Firebase فقط | ذاكرة + Firebase |
| **خدمة الإيميل** | `send_email_otp()` محلية | `email_service.py` |
| **تصميم الإيميل** | بنفسجي/أبيض | أسود/أخضر نيون |
| **صلاحية الكود** | 10 دقائق | 5 دقائق |
| **Fallback** | Telegram | Telegram |
| **يرجع user_id** | ❌ | ✅ |

**ملاحظة:** يمكنك استخدام أي منهما حسب احتياجك. الأول أبسط، والثاني فيه ميزات أكثر.

---

## 🗄️ بنية Firebase المطلوبة

```javascript
// Firebase > Firestore > users > {user_id}
{
    "username": "Sbras_1",
    "first_name": "سعد",
    "email": "user@example.com",      // ← مطلوب للدخول بالإيميل
    "verification_code": "123456",     // يتم توليده عند الطلب
    "code_time": 1707177600,           // وقت إنشاء الكود (timestamp)
    "balance": 0.0
}
```

---

## 🔒 الأمان

| الميزة | التفاصيل |
|--------|----------|
| صلاحية الكود | 10 دقائق فقط |
| مسح الكود | بعد الاستخدام الناجح |
| SSL/TLS | اتصال مشفر مع SMTP |
| Session Timeout | 30 دقيقة |
| Session Regeneration | تجديد الجلسة عند الدخول |
| Rate Limiting | حماية من المحاولات المتكررة |
| login_time | ⚠️ مهم لمنع انتهاء الجلسة فوراً |

---

## 🔧 استكشاف الأخطاء

### الخطأ: "Username and Password not accepted"
- **السبب**: كلمة مرور SMTP خاطئة
- **الحل**: تحقق من `SMTP_PASSWORD` في Render

### الخطأ: "لا يوجد حساب مرتبط بهذا البريد"
- **السبب**: الإيميل غير موجود في Firebase
- **الحل**: أضف حقل `email` للمستخدم في Firestore

### الخطأ: "انتهت صلاحية الكود"
- **السبب**: مر أكثر من 10 دقائق
- **الحل**: اطلب كود جديد

### الجلسة تنتهي فوراً بعد الدخول
- **السبب**: `login_time` غير موجود في الجلسة
- **الحل**: تأكد من إضافة `session['login_time'] = time.time()`

### الإيميل لا يصل
- **السبب**: إعدادات DNS غير مكتملة (للدومين الخاص)
- **الحل**: تحقق من إضافة MX و SPF records

---

## 📝 ملاحظات مهمة

1. **الكود يدعم** Namecheap Private Email و Gmail
2. **يمكن تغيير مزود SMTP** من Environment Variables فقط
3. **Fallback للتلغرام** إذا فشل إرسال الإيميل
4. **قالب HTML جميل** للإيميل مع تدرج لوني

---

## � الدوال المساعدة المطلوبة

### دالة توليد الكود العشوائي

**الملف:** `utils.py`
**الوظيفة:** توليد كود مكون من 6 أرقام

```python
import random

def generate_code():
    """توليد كود تحقق عشوائي من 6 أرقام"""
    return str(random.randint(100000, 999999))
```

---

### دالة تجديد الجلسة

**الملف:** `utils.py`
**الوظيفة:** تجديد الجلسة للأمان عند تسجيل الدخول (منع Session Fixation Attack)

```python
from flask import session

def regenerate_session():
    """تجديد ID الجلسة لمنع Session Fixation"""
    # حفظ كل البيانات الحالية
    old_data = dict(session)
    
    # مسح الجلسة القديمة (يولّد session ID جديد)
    session.clear()
    
    # إعادة كل البيانات للجلسة الجديدة
    session.update(old_data)
    
    # إجبار حفظ التغييرات
    session.modified = True
```

**ملاحظة أمنية:** هذه الدالة تُستدعى عند تسجيل الدخول الناجح لمنع هجمات Session Fixation حيث يحاول المهاجم تثبيت session ID معين قبل تسجيل الدخول.

---

## ⚙️ إعدادات Session في config.py

**الملف:** `config.py`
**المكان:** أضف مع الإعدادات الأخرى

```python
from datetime import timedelta

# === إعدادات الجلسة ===
SESSION_CONFIG = {
    'SESSION_COOKIE_SECURE': True,  # HTTPS فقط
    'SESSION_COOKIE_HTTPONLY': True,  # منع JavaScript من الوصول
    'SESSION_COOKIE_SAMESITE': 'Lax',  # حماية CSRF
    'PERMANENT_SESSION_LIFETIME': timedelta(minutes=30),  # 30 دقيقة
    'SESSION_COOKIE_NAME': 'tr_session',
}
```

**ثم في `app.py`:**
```python
from config import SESSION_CONFIG

app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key")
app.config.update(SESSION_CONFIG)
```

---

## 🔗 تسجيل Blueprint في app.py

**الملف:** `app.py`
**المكان:** مع باقي الـ blueprints

```python
# في أعلى الملف - Import
from routes.auth_routes import auth_bp

# بعد إنشاء app - Registration
app.register_blueprint(auth_bp)
```

**ملاحظة:** تأكد أن ملف `routes/auth_routes.py` يحتوي على:
```python
from flask import Blueprint

auth_bp = Blueprint('auth', __name__)
```

---

## 🎨 CSS للواجهة

**الملف:** `templates/categories.html` أو `static/css/style.css`

```css
/* === نموذج تسجيل الدخول === */
.login-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
}

.login-container {
    background: white;
    border-radius: 20px;
    padding: 30px;
    width: 90%;
    max-width: 400px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

/* الخطوات */
.step {
    display: none;
}

.step.active {
    display: block;
}

/* حقول الإدخال */
.login-container input {
    width: 100%;
    padding: 15px;
    border: 2px solid #e0e0e0;
    border-radius: 12px;
    font-size: 16px;
    margin-bottom: 15px;
    transition: border-color 0.3s;
}

.login-container input:focus {
    border-color: #667eea;
    outline: none;
}

/* حقل الكود */
.code-input {
    text-align: center;
    font-size: 24px !important;
    letter-spacing: 8px;
    font-weight: bold;
}

/* الأزرار */
.login-container button {
    width: 100%;
    padding: 15px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
}

.login-container button:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
}

.login-container button:disabled {
    background: #ccc;
    cursor: not-allowed;
    transform: none;
}

/* رسائل الخطأ */
.error-msg {
    background: #fee;
    color: #c00;
    padding: 10px 15px;
    border-radius: 8px;
    margin-top: 10px;
    display: none;
    font-size: 14px;
}

/* رسائل النجاح */
.success-msg {
    background: #efe;
    color: #080;
    padding: 10px 15px;
    border-radius: 8px;
    margin-top: 10px;
    display: none;
    font-size: 14px;
}

/* العد التنازلي */
.countdown {
    text-align: center;
    color: #666;
    font-size: 14px;
    margin-top: 15px;
}

.countdown span {
    color: #667eea;
    font-weight: bold;
}
```

---

## 🛡️ نظام الحماية من المحاولات المتكررة (Rate Limiting)

**الملف:** `routes/auth_routes.py`
**الوظيفة:** حماية من هجمات Brute Force على تسجيل الدخول

### كيف يعمل؟

1. **تتبع المحاولات الفاشلة** بناءً على IP
2. **5 محاولات فاشلة** → حظر 15 دقيقة
3. **إعادة تعيين** العداد بعد 15 دقيقة من آخر محاولة
4. **مسح العداد** عند تسجيل دخول ناجح

### الكود:

```python
# تخزين مؤقت لمحاولات الدخول الفاشلة
login_failed_attempts = {}  # {ip: {'count': 0, 'blocked_until': 0, 'last_attempt': 0}}

def check_login_rate_limit():
    """التحقق من rate limit لتسجيل الدخول"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    current_time = time.time()
    
    if client_ip in login_failed_attempts:
        attempt_data = login_failed_attempts[client_ip]
        
        # التحقق من الحظر
        if attempt_data.get('blocked_until', 0) > current_time:
            remaining = int(attempt_data['blocked_until'] - current_time)
            return False, f'⛔ تم حظرك مؤقتاً. حاول بعد {remaining} ثانية'
        
        # إعادة تعيين العداد بعد 15 دقيقة من آخر محاولة
        if current_time - attempt_data.get('last_attempt', 0) > 900:
            login_failed_attempts[client_ip] = {'count': 0, 'blocked_until': 0, 'last_attempt': current_time}
    
    return True, None

def record_failed_login():
    """تسجيل محاولة دخول فاشلة"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    current_time = time.time()
    
    if client_ip not in login_failed_attempts:
        login_failed_attempts[client_ip] = {'count': 0, 'blocked_until': 0, 'last_attempt': current_time}
    
    login_failed_attempts[client_ip]['count'] += 1
    login_failed_attempts[client_ip]['last_attempt'] = current_time
    
    attempts = login_failed_attempts[client_ip]['count']
    
    # حظر بعد 5 محاولات فاشلة لمدة 15 دقيقة
    if attempts >= 5:
        login_failed_attempts[client_ip]['blocked_until'] = current_time + 900  # 15 دقيقة
        return 0
    
    return 5 - attempts  # عدد المحاولات المتبقية

def reset_login_attempts():
    """إعادة تعيين عداد المحاولات بعد دخول ناجح"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    if client_ip in login_failed_attempts:
        del login_failed_attempts[client_ip]
```

### استخدام في الـ Endpoint:

```python
@auth_bp.route('/login', methods=['POST'])
def login():
    # 🔒 التحقق من Rate Limit أولاً
    allowed, error_msg = check_login_rate_limit()
    if not allowed:
        return jsonify({'success': False, 'message': error_msg})
    
    # ... باقي الكود ...
    
    if login_failed:
        remaining = record_failed_login()
        return jsonify({'success': False, 'message': f'كود خاطئ. متبقي {remaining} محاولات'})
    
    # عند النجاح
    reset_login_attempts()
```

---

## 📧 خدمة البريد الإلكتروني المنفصلة (اختياري)

**الملف:** `services/email_service.py`
**الوظيفة:** خدمة إيميل متقدمة مع تصميم مختلف (أسود/أخضر)

### ملاحظة:
هذا الملف موجود كبديل/إضافة لـ `send_email_otp()` في `auth_routes.py`. يمكنك استخدام أي منهما.

### الدوال المتوفرة:

| الدالة | الوظيفة |
|--------|--------|
| `is_email_configured()` | التحقق من إعداد SMTP |
| `send_otp_email(to, code, name)` | إرسال كود التحقق |
| `send_notification_email(to, subject, msg)` | إرسال إشعار عام |

### الاختلاف عن auth_routes:

| البند | `auth_routes.py` | `email_service.py` |
|-------|------------------|--------------------|
| التصميم | بنفسجي/أبيض | أسود/أخضر نيون |
| صلاحية الكود | 10 دقائق | 5 دقائق (في النص) |
| الاتصال | SSL ثم TLS | TLS فقط |

### كود مختصر:

```python
# services/email_service.py
from config import SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD, SMTP_FROM_NAME

def is_email_configured():
    """التحقق من إعداد خدمة البريد الإلكتروني"""
    return bool(SMTP_EMAIL and SMTP_PASSWORD)

def send_otp_email(to_email, otp_code, user_name="عميلنا العزيز"):
    """إرسال كود التحقق عبر البريد الإلكتروني"""
    if not is_email_configured():
        return False
    
    # ... إعداد الرسالة مع تصميم HTML ...
    
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
    
    return True
```

---

## 🌐 إعداد DNS لـ Namecheap Private Email

إذا كنت تستخدم دومين خاص (مثل `gamerstr1.com`)، يجب إضافة سجلات DNS:

### الخطوات:

1. اذهب إلى **Namecheap** → **Dashboard**
2. اضغط على **Domain List**
3. بجانب الدومين اضغط **Manage**
4. اضغط على **Advanced DNS**
5. أضف السجلات التالية:

### سجلات MX (للاستقبال):

| Type | Host | Value | Priority |
|------|------|-------|----------|
| MX | @ | mx1.privateemail.com | 10 |
| MX | @ | mx2.privateemail.com | 10 |

### سجل SPF (للإرسال):

| Type | Host | Value |
|------|------|-------|
| TXT | @ | v=spf1 include:spf.privateemail.com ~all |

### سجل DKIM (اختياري - لتحسين التسليم):

| Type | Host | Value |
|------|------|-------|
| TXT | default._domainkey | (احصل عليه من Namecheap Email Settings) |

### ملاحظات:
- انتظر **1-4 ساعات** حتى تنتشر الإعدادات
- يمكنك التحقق من https://mxtoolbox.com/

---

## 📁 الملفات المتعلقة

```
├── config.py                    # إعدادات SMTP + Session + SMTP_FROM_NAME
├── utils.py                     # generate_code() + regenerate_session()
├── app.py                       # تسجيل Blueprint + Session config
├── routes/auth_routes.py        # API endpoints + إرسال الإيميل + Rate Limiting
├── services/email_service.py    # خدمة إيميل بديلة (تصميم أسود/أخضر)
├── templates/categories.html    # واجهة المستخدم
└── static/css/style.css         # التنسيقات (اختياري)
```

---

## ✅ قائمة التحقق قبل التشغيل

### الإعدادات:
- [ ] إضافة إعدادات SMTP في `config.py`
- [ ] إضافة `SMTP_FROM_NAME` في `config.py`
- [ ] إضافة إعدادات Session في `config.py`

### الدوال المساعدة:
- [ ] إضافة `generate_code()` في `utils.py`
- [ ] إضافة `regenerate_session()` في `utils.py`

### نظام المصادقة:
- [ ] إضافة imports في `routes/auth_routes.py`
- [ ] إضافة Rate Limiting (check, record, reset)
- [ ] إضافة دالة `send_email_otp()` في `routes/auth_routes.py`
- [ ] إضافة endpoint `/api/auth/send-code`
- [ ] إضافة endpoint `/api/auth/login`

### التكامل:
- [ ] تسجيل Blueprint في `app.py`
- [ ] تطبيق Session config في `app.py`

### الواجهة:
- [ ] إضافة HTML + JavaScript في الواجهة
- [ ] إضافة CSS للتنسيق

### البيئة:
- [ ] إعداد Environment Variables في Render (5 متغيرات)
- [ ] إضافة حقل `email` للمستخدمين في Firebase
- [ ] إعداد DNS (إذا كان دومين خاص)

---

**تاريخ التحديث:** فبراير 2026
