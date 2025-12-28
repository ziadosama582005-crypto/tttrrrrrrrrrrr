#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حزمة معالجات بوت التيليجرام
============================
تصدير جميع معالجات البوت
"""

from .telegram_handlers import register_telegram_handlers

__all__ = ['register_telegram_handlers']
