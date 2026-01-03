"""
🔐 Encryption Utilities - أدوات التشفير
تشفير AES-128 باستخدام Fernet
"""

import os
import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# مفتاح التشفير من Environment Variables
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

# كائن Fernet للتشفير
_fernet = None

def get_fernet():
    """الحصول على كائن Fernet للتشفير"""
    global _fernet
    
    if _fernet is None:
        if not ENCRYPTION_KEY:
            print("⚠️ تحذير: ENCRYPTION_KEY غير موجود! التشفير معطل.")
            return None
        
        try:
            # التحقق من صحة المفتاح
            _fernet = Fernet(ENCRYPTION_KEY.encode())
        except Exception as e:
            print(f"❌ خطأ في مفتاح التشفير: {e}")
            return None
    
    return _fernet


def encrypt_data(data: str) -> str:
    """
    تشفير نص
    
    Args:
        data: النص المراد تشفيره
        
    Returns:
        النص المشفر (base64) أو النص الأصلي إذا فشل التشفير
    """
    if not data:
        return data
    
    fernet = get_fernet()
    if not fernet:
        # إذا لم يوجد مفتاح، إرجاع النص كما هو (للتوافق)
        return data
    
    try:
        encrypted = fernet.encrypt(data.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        print(f"❌ خطأ في التشفير: {e}")
        return data


def decrypt_data(encrypted_data: str) -> str:
    """
    فك تشفير نص
    
    Args:
        encrypted_data: النص المشفر
        
    Returns:
        النص الأصلي أو النص المشفر إذا فشل فك التشفير
    """
    if not encrypted_data:
        return encrypted_data
    
    fernet = get_fernet()
    if not fernet:
        # إذا لم يوجد مفتاح، إرجاع النص كما هو
        return encrypted_data
    
    try:
        decrypted = fernet.decrypt(encrypted_data.encode('utf-8'))
        return decrypted.decode('utf-8')
    except InvalidToken:
        # النص غير مشفر أو مفتاح خاطئ - إرجاعه كما هو
        return encrypted_data
    except Exception as e:
        print(f"❌ خطأ في فك التشفير: {e}")
        return encrypted_data


def encrypt_dict_fields(data: dict, fields: list) -> dict:
    """
    تشفير حقول محددة في قاموس
    
    Args:
        data: القاموس
        fields: قائمة الحقول المراد تشفيرها
        
    Returns:
        القاموس مع الحقول المشفرة
    """
    encrypted_data = data.copy()
    
    for field in fields:
        if field in encrypted_data and encrypted_data[field]:
            encrypted_data[field] = encrypt_data(str(encrypted_data[field]))
    
    return encrypted_data


def decrypt_dict_fields(data: dict, fields: list) -> dict:
    """
    فك تشفير حقول محددة في قاموس
    
    Args:
        data: القاموس
        fields: قائمة الحقول المراد فك تشفيرها
        
    Returns:
        القاموس مع الحقول مفكوكة التشفير
    """
    decrypted_data = data.copy()
    
    for field in fields:
        if field in decrypted_data and decrypted_data[field]:
            decrypted_data[field] = decrypt_data(str(decrypted_data[field]))
    
    return decrypted_data


def generate_new_key() -> str:
    """
    توليد مفتاح تشفير جديد
    
    Returns:
        مفتاح Fernet جديد (base64)
    """
    return Fernet.generate_key().decode('utf-8')


def is_encrypted(data: str) -> bool:
    """
    التحقق مما إذا كان النص مشفراً
    
    Args:
        data: النص للفحص
        
    Returns:
        True إذا كان مشفراً
    """
    if not data:
        return False
    
    # Fernet tokens تبدأ بـ gAAAAA
    return data.startswith('gAAAAA')


# الحقول التي يجب تشفيرها
ENCRYPTED_FIELDS = [
    'totp_secret',      # مفتاح المصادقة الثنائية
    'email',            # البريد الإلكتروني
    'phone',            # رقم الهاتف
    'address',          # العنوان
    'balance',          # الرصيد (كنص)
    'hidden_data',      # بيانات المنتج السرية
    'iban',             # رقم الآيبان للسحب
    'wallet_number',    # رقم المحفظة الإلكترونية
]


def encrypt_user_data(user_data: dict) -> dict:
    """تشفير بيانات المستخدم الحساسة"""
    return encrypt_dict_fields(user_data, ENCRYPTED_FIELDS)


def decrypt_user_data(user_data: dict) -> dict:
    """فك تشفير بيانات المستخدم"""
    return decrypt_dict_fields(user_data, ENCRYPTED_FIELDS)


# ===== للاختبار =====
if __name__ == '__main__':
    # توليد مفتاح جديد
    new_key = generate_new_key()
    print(f"🔑 مفتاح جديد: {new_key}")
    
    # اختبار التشفير
    os.environ['ENCRYPTION_KEY'] = new_key
    _fernet = None  # إعادة تعيين
    
    test_data = "secret_totp_key_12345"
    encrypted = encrypt_data(test_data)
    decrypted = decrypt_data(encrypted)
    
    print(f"📝 الأصلي: {test_data}")
    print(f"🔒 مشفر: {encrypted}")
    print(f"🔓 مفكوك: {decrypted}")
    print(f"✅ نجاح: {test_data == decrypted}")
