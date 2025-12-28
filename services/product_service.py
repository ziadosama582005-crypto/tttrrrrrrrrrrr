#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خدمات المنتجات
===============
دوال التعامل مع المنتجات والفئات
"""

import uuid
from firebase_admin import firestore

class ProductService:
    """خدمة المنتجات"""
    
    def __init__(self, db, firebase_utils):
        """
        تهيئة خدمة المنتجات
        
        Parameters:
        -----------
        db : firestore.client
            عميل Firebase
        firebase_utils : module
            أدوات Firebase
        """
        self.db = db
        self.firebase_utils = firebase_utils
    
    def add_product(self, product_data):
        """إضافة منتج جديد"""
        try:
            if not self.db:
                return False
            
            product_id = str(uuid.uuid4())
            product_data['id'] = product_id
            product_data['sold'] = False
            product_data['created_at'] = firestore.SERVER_TIMESTAMP
            
            self.db.collection('products').document(product_id).set(product_data)
            print(f"✅ تم إضافة المنتج: {product_id}")
            return product_id
        except Exception as e:
            print(f"❌ خطأ في إضافة المنتج: {e}")
            return False
    
    def get_all_products(self):
        """جلب جميع المنتجات"""
        return self.firebase_utils.get_all_products_for_store()
    
    def get_product(self, product_id):
        """جلب منتج معين"""
        return self.firebase_utils.get_product_by_id(product_id)
    
    def update_product(self, product_id, data):
        """تحديث بيانات المنتج"""
        return self.firebase_utils.update_product(product_id, data)
    
    def delete_product(self, product_id):
        """حذف منتج"""
        return self.firebase_utils.delete_product(product_id)
    
    def get_categories(self):
        """جلب جميع الفئات"""
        return self.firebase_utils.get_categories()
    
    def add_category(self, category_data):
        """إضافة فئة جديدة"""
        return self.firebase_utils.add_category(category_data)
