#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خدمات المستخدمين
=================
دوال التعامل مع بيانات المستخدمين
"""

class UserService:
    """خدمة المستخدمين"""
    
    def __init__(self, db, firebase_utils):
        """
        تهيئة خدمة المستخدمين
        
        Parameters:
        -----------
        db : firestore.client
            عميل Firebase
        firebase_utils : module
            أدوات Firebase
        """
        self.db = db
        self.firebase_utils = firebase_utils
    
    def get_user(self, user_id):
        """جلب بيانات المستخدم"""
        try:
            if not self.db:
                return None
            doc = self.db.collection('users').document(str(user_id)).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            print(f"❌ خطأ في جلب المستخدم: {e}")
            return None
    
    def get_balance(self, user_id):
        """جلب رصيد المستخدم"""
        return self.firebase_utils.get_balance(str(user_id))
    
    def add_balance(self, user_id, amount):
        """إضافة رصيد للمستخدم"""
        return self.firebase_utils.add_balance(str(user_id), amount)
    
    def deduct_balance(self, user_id, amount):
        """خصم رصيد من المستخدم"""
        return self.firebase_utils.deduct_balance(str(user_id), amount)
