#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خدمات الدفع
===========
دوال التعامل مع نظام الدفع والفواتير
"""

class PaymentService:
    """خدمة معالجة الدفع"""
    
    def __init__(self, db, payment_utils):
        """
        تهيئة خدمة الدفع
        
        Parameters:
        -----------
        db : firestore.client
            عميل Firebase
        payment_utils : module
            أدوات نظام الدفع
        """
        self.db = db
        self.payment_utils = payment_utils
    
    def create_invoice(self, order_id, amount, description, user_id):
        """إنشاء فاتورة دفع"""
        try:
            payload = self.payment_utils.create_payment_payload(
                order_id=order_id,
                amount=amount,
                description=description,
                user_id=user_id
            )
            return payload
        except Exception as e:
            print(f"❌ خطأ في إنشاء الفاتورة: {e}")
            return None
    
    def calculate_hash(self, order_id, amount, description):
        """حساب Hash للدفع الآمن"""
        return self.payment_utils.calculate_hash(order_id, amount, description)
    
    def verify_payment(self, order_id, amount):
        """التحقق من صحة الدفع"""
        try:
            if not self.db:
                return False
            
            doc = self.db.collection('payments').document(order_id).get()
            if doc.exists:
                data = doc.to_dict()
                return data.get('amount') == amount
            return False
        except Exception as e:
            print(f"❌ خطأ في التحقق من الدفع: {e}")
            return False
