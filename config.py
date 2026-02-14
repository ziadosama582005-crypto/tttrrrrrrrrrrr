#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import secrets
from datetime import timedelta

ADMIN_ID = int(os.environ.get("ADMIN_ID", 123456789))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "default_token_123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000")

VERIFIED_CHANNEL_ID = os.environ.get("VERIFIED_CHANNEL_ID", "")
ACTIVITY_CHANNEL_ID = os.environ.get("ACTIVITY_CHANNEL_ID", "")

CONTACT_BOT_URL = os.environ.get("CONTACT_BOT_URL", "https://t.me/GamersTR_bot")
CONTACT_WHATSAPP = os.environ.get("CONTACT_WHATSAPP", "https://wa.me/966504104956")

EDFAPAY_MERCHANT_ID = os.environ.get("EDFAPAY_MERCHANT_ID", "")
EDFAPAY_PASSWORD = os.environ.get("EDFAPAY_PASSWORD", "")
EDFAPAY_API_URL = "https://api.edfapay.com/payment/initiate"

FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS")
FIREBASE_CREDENTIALS_FILE = "serviceAccountKey.json"

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "your-secret-key-here-change-it":
    SECRET_KEY = secrets.token_hex(32)

IS_PRODUCTION = os.environ.get("RENDER", False) or os.environ.get("PRODUCTION", False)

SESSION_CONFIG = {
    'SESSION_COOKIE_SECURE': IS_PRODUCTION,
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Strict',
    'PERMANENT_SESSION_LIFETIME': timedelta(minutes=30),
    'SESSION_COOKIE_NAME': 'tr_session',
}

RATE_LIMIT_DEFAULT = ["200 per day", "50 per hour"]
RATE_LIMIT_STORAGE = "memory://"

CART_EXPIRY_HOURS = 1

DEFAULT_CATEGORIES = [
    {'id': '1', 'name': 'نتفلكس', 'image_url': 'https://i.imgur.com/netflix.png', 'order': 1, 'delivery_type': 'instant'},
    {'id': '2', 'name': 'شاهد', 'image_url': 'https://i.imgur.com/shahid.png', 'order': 2, 'delivery_type': 'instant'},
    {'id': '3', 'name': 'ديزني بلس', 'image_url': 'https://i.imgur.com/disney.png', 'order': 3, 'delivery_type': 'instant'},
    {'id': '4', 'name': 'اوسن بلس', 'image_url': 'https://i.imgur.com/osn.png', 'order': 4, 'delivery_type': 'instant'},
    {'id': '5', 'name': 'فديو بريميم', 'image_url': 'https://i.imgur.com/vedio.png', 'order': 5, 'delivery_type': 'instant'},
    {'id': '6', 'name': 'اشتراكات أخرى', 'image_url': 'https://i.imgur.com/other.png', 'order': 6, 'delivery_type': 'manual'}
]

DISPLAY_SETTINGS = {
    'categories_columns': 3
}

SMTP_SERVER = os.environ.get("SMTP_SERVER", "mail.privateemail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "TR Store")

AUTHENTICA_API_KEY = os.environ.get("AUTHENTICA_API_KEY", "")
AUTHENTICA_API_URL = "https://api.authentica.sa/api/v2"
AUTHENTICA_DEFAULT_METHOD = os.environ.get("AUTHENTICA_METHOD", "sms")
AUTHENTICA_TEMPLATE_ID = os.environ.get("AUTHENTICA_TEMPLATE_ID", "1")
