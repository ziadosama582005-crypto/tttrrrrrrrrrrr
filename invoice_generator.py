# -*- coding: utf-8 -*-
"""
مولّد فواتير السحب بصيغة PDF
يُنشئ فاتورة احترافية عند الموافقة على طلب سحب ويرسلها بالبريد الإلكتروني
"""

import io
import os
import logging
import threading
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from fpdf import FPDF

logger = logging.getLogger(__name__)

# مسار الخطوط العربية
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fonts')
FONT_REGULAR = os.path.join(FONTS_DIR, 'Amiri-Regular.ttf')
FONT_BOLD = os.path.join(FONTS_DIR, 'Amiri-Bold.ttf')


class WithdrawalInvoicePDF(FPDF):
    """فاتورة سحب احترافية"""

    def __init__(self, withdrawal_data: dict):
        super().__init__()
        self.withdrawal_data = withdrawal_data
        self._setup_fonts()

    def _setup_fonts(self):
        """تهيئة الخطوط العربية"""
        if os.path.exists(FONT_REGULAR):
            self.add_font('Amiri', '', FONT_REGULAR)
        if os.path.exists(FONT_BOLD):
            self.add_font('Amiri', 'B', FONT_BOLD)
        self.set_text_shaping(True)

    def header(self):
        """ترويسة الفاتورة"""
        # خلفية الترويسة
        self.set_fill_color(102, 126, 234)  # #667eea
        self.rect(0, 0, 210, 45, 'F')

        # اسم المتجر
        self.set_font('Amiri', 'B', 28)
        self.set_text_color(255, 255, 255)
        self.set_y(8)
        self.cell(0, 12, 'TR Store', align='C', new_x='LEFT', new_y='NEXT')

        # عنوان الفاتورة
        self.set_font('Amiri', '', 16)
        self.set_text_color(230, 230, 255)
        self.cell(0, 10, 'إيصال سحب رصيد', align='C', new_x='LEFT', new_y='NEXT')

        self.ln(15)

    def footer(self):
        """تذييل الفاتورة"""
        self.set_y(-30)
        self.set_draw_color(200, 200, 200)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(5)
        self.set_font('Amiri', '', 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, 'هذا إيصال إلكتروني صادر تلقائياً من TR Store', align='C', new_x='LEFT', new_y='NEXT')
        self.cell(0, 5, f'تاريخ الإصدار: {datetime.now().strftime("%Y-%m-%d %H:%M")}', align='C', new_x='LEFT', new_y='NEXT')

    def _draw_info_row(self, label: str, value: str, is_highlight: bool = False):
        """رسم صف معلومات"""
        row_h = 12
        if is_highlight:
            self.set_fill_color(240, 245, 255)
            self.rect(15, self.get_y(), 180, row_h, 'F')

        self.set_font('Amiri', 'B', 12)
        self.set_text_color(100, 100, 100)
        # القيمة على اليسار
        self.cell(90, row_h, value, align='L')
        # التسمية على اليمين
        self.set_text_color(60, 60, 60)
        self.cell(90, row_h, label, align='R', new_x='LEFT', new_y='NEXT')

    def _draw_amount_row(self, label: str, amount: float, is_total: bool = False):
        """رسم صف مبلغ"""
        row_h = 14 if is_total else 12
        if is_total:
            self.set_fill_color(102, 126, 234)
            self.rect(15, self.get_y(), 180, row_h, 'F')
            self.set_font('Amiri', 'B', 14)
            self.set_text_color(255, 255, 255)
        else:
            self.set_fill_color(248, 249, 250)
            self.rect(15, self.get_y(), 180, row_h, 'F')
            self.set_font('Amiri', '', 12)
            self.set_text_color(60, 60, 60)

        self.cell(90, row_h, f'{amount:.2f} ر.س', align='L')
        self.cell(90, row_h, label, align='R', new_x='LEFT', new_y='NEXT')

    def build(self) -> bytes:
        """بناء الفاتورة وإرجاعها كـ bytes"""
        data = self.withdrawal_data
        self.add_page()

        # === معلومات الفاتورة ===
        self.set_font('Amiri', 'B', 14)
        self.set_text_color(102, 126, 234)
        self.cell(0, 10, 'معلومات الطلب', align='R', new_x='LEFT', new_y='NEXT')
        self.set_draw_color(102, 126, 234)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)

        # رقم الطلب
        withdrawal_id = data.get('withdrawal_id', 'N/A')
        self._draw_info_row('رقم الإيصال', f'#{withdrawal_id[:12]}' if len(str(withdrawal_id)) > 12 else f'#{withdrawal_id}', True)

        # تاريخ الطلب
        created_at = data.get('created_at')
        if created_at:
            if hasattr(created_at, 'strftime'):
                date_str = created_at.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = str(created_at)
        else:
            date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        self._draw_info_row('تاريخ الطلب', date_str, False)

        # تاريخ الموافقة
        approved_at = data.get('approved_at')
        if approved_at:
            if hasattr(approved_at, 'strftime'):
                approved_str = approved_at.strftime('%Y-%m-%d %H:%M')
            else:
                approved_str = str(approved_at)
        else:
            approved_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        self._draw_info_row('تاريخ الموافقة', approved_str, True)

        # الحالة
        self._draw_info_row('الحالة', '✓ تمت الموافقة', False)

        # اسم المستفيد
        full_name = data.get('full_name', 'غير محدد')
        self._draw_info_row('اسم المستفيد', full_name, True)

        self.ln(8)

        # === تفاصيل المبالغ ===
        self.set_font('Amiri', 'B', 14)
        self.set_text_color(102, 126, 234)
        self.cell(0, 10, 'تفاصيل المبلغ', align='R', new_x='LEFT', new_y='NEXT')
        self.set_draw_color(102, 126, 234)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)

        amount = data.get('amount', 0)
        fee = data.get('fee', 0)
        fee_percentage = data.get('fee_percentage', 0)
        net_amount = data.get('net_amount', 0)

        self._draw_amount_row('المبلغ المطلوب', amount)
        fee_label = f'رسوم الخدمة ({fee_percentage}%)' if fee_percentage else 'رسوم الخدمة'
        self._draw_amount_row(fee_label, fee)
        self.ln(2)
        self._draw_amount_row('المبلغ الصافي', net_amount, is_total=True)

        self.ln(10)

        # === طريقة التحويل ===
        self.set_font('Amiri', 'B', 14)
        self.set_text_color(102, 126, 234)
        self.cell(0, 10, 'طريقة التحويل', align='R', new_x='LEFT', new_y='NEXT')
        self.set_draw_color(102, 126, 234)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)

        withdrawal_type = data.get('withdrawal_type', 'bank')

        if withdrawal_type == 'bank':
            self._draw_info_row('طريقة السحب', 'تحويل بنكي', True)
            bank_name = data.get('bank_name', 'غير محدد')
            iban = data.get('iban', 'غير محدد')
            self._draw_info_row('البنك', bank_name, False)
            self._draw_info_row('رقم الآيبان (IBAN)', iban, True)
        else:
            self._draw_info_row('طريقة السحب', 'محفظة إلكترونية', True)
            wallet_type = data.get('wallet_type', 'غير محدد')
            wallet_number = data.get('wallet_number', 'غير محدد')
            self._draw_info_row('نوع المحفظة', wallet_type, False)
            self._draw_info_row('رقم المحفظة', wallet_number, True)

        self.ln(12)

        # === ملاحظة ===
        self.set_fill_color(255, 249, 230)
        self.set_draw_color(255, 193, 7)
        note_y = self.get_y()
        self.rect(15, note_y, 180, 22, 'DF')
        self.set_font('Amiri', '', 11)
        self.set_text_color(120, 100, 0)
        self.set_y(note_y + 3)
        self.cell(0, 8, 'سيتم تحويل المبلغ خلال 24-48 ساعة عمل إلى الحساب المحدد أعلاه.', align='C', new_x='LEFT', new_y='NEXT')
        self.cell(0, 8, 'في حال وجود أي استفسار يرجى التواصل مع الدعم الفني.', align='C', new_x='LEFT', new_y='NEXT')

        # إخراج PDF كـ bytes
        return self.output()


def generate_withdrawal_invoice(withdrawal_data: dict) -> bytes:
    """
    إنشاء فاتورة سحب PDF

    Args:
        withdrawal_data: بيانات طلب السحب (من Firestore)
            - withdrawal_id, amount, fee, fee_percentage, net_amount
            - withdrawal_type, bank_name, iban, wallet_type, wallet_number
            - full_name, created_at, approved_at, status

    Returns:
        bytes: محتوى ملف PDF
    """
    try:
        pdf = WithdrawalInvoicePDF(withdrawal_data)
        return pdf.build()
    except Exception as e:
        logger.error(f"❌ فشل إنشاء فاتورة السحب: {e}")
        return None


def send_withdrawal_invoice_email(to_email: str, withdrawal_data: dict):
    """
    إنشاء فاتورة PDF وإرسالها بالبريد الإلكتروني (في thread منفصل)

    Args:
        to_email: بريد المستخدم
        withdrawal_data: بيانات طلب السحب
    """
    def _send():
        try:
            from config import SMTP_SERVER, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD

            if not SMTP_EMAIL or not SMTP_PASSWORD or not to_email:
                logger.warning("⚠️ لا يمكن إرسال فاتورة السحب: بيانات SMTP أو البريد ناقصة")
                return

            # إنشاء PDF
            pdf_bytes = generate_withdrawal_invoice(withdrawal_data)
            if not pdf_bytes:
                logger.error("❌ فشل إنشاء ملف PDF للفاتورة")
                return

            # بناء الإيميل
            net_amount = withdrawal_data.get('net_amount', 0)
            withdrawal_id = withdrawal_data.get('withdrawal_id', 'N/A')

            msg = MIMEMultipart('mixed')
            msg['From'] = f"TR Store <{SMTP_EMAIL}>"
            msg['To'] = to_email
            msg['Subject'] = f"✅ إيصال سحب رصيد — {net_amount:.2f} ر.س | TR Store"

            # نص HTML للإيميل
            html_body = f"""
            <!DOCTYPE html>
            <html dir="rtl">
            <head><meta charset="UTF-8"></head>
            <body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Tahoma,sans-serif;">
                <div style="max-width:550px;margin:30px auto;background:#fff;border-radius:20px;box-shadow:0 10px 40px rgba(0,0,0,0.1);overflow:hidden;">
                    <div style="background:linear-gradient(135deg,#667eea,#764ba2);padding:30px;text-align:center;">
                        <h1 style="color:#fff;margin:0;font-size:24px;">✅ تمت الموافقة على طلب السحب</h1>
                        <p style="color:rgba(255,255,255,0.9);margin:8px 0 0;font-size:14px;">إيصال سحب رصيد من TR Store</p>
                    </div>
                    <div style="padding:24px;">
                        <div style="background:#f0fff4;border:2px solid #00b894;border-radius:12px;padding:20px;text-align:center;margin-bottom:16px;">
                            <span style="color:#00b894;font-size:14px;">المبلغ الصافي</span><br>
                            <span style="color:#00b894;font-size:32px;font-weight:800;">{net_amount:.2f} ر.س</span>
                        </div>
                        <div style="background:#f8f9fa;border-radius:10px;padding:14px;margin-bottom:10px;">
                            <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                                <span style="color:#666;">رقم الطلب:</span>
                                <span style="font-weight:700;">#{withdrawal_id[:12] if len(str(withdrawal_id)) > 12 else withdrawal_id}</span>
                            </div>
                            <div style="display:flex;justify-content:space-between;">
                                <span style="color:#666;">المبلغ المطلوب:</span>
                                <span style="font-weight:700;">{withdrawal_data.get('amount', 0):.2f} ر.س</span>
                            </div>
                        </div>
                        <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:10px;padding:12px;text-align:center;">
                            <span style="font-size:13px;color:#f57f17;">📎 الفاتورة مرفقة بصيغة PDF</span>
                        </div>
                    </div>
                    <div style="background:#f8f9fa;padding:16px;text-align:center;border-top:1px solid #eee;">
                        <p style="color:#aaa;font-size:11px;margin:0;">سيتم تحويل المبلغ خلال 24-48 ساعة عمل</p>
                        <p style="color:#ccc;font-size:11px;margin:6px 0 0;">TR Store © {datetime.now().year}</p>
                    </div>
                </div>
            </body>
            </html>"""

            # إرفاق HTML
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)

            # إرفاق PDF
            pdf_attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
            pdf_filename = f"withdrawal_invoice_{withdrawal_id[:12]}.pdf"
            pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
            msg.attach(pdf_attachment)

            # إرسال الإيميل
            try:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    logger.info(f"✅ تم إرسال فاتورة السحب إلى: {to_email}")
            except Exception:
                with smtplib.SMTP(SMTP_SERVER, 587, timeout=15) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)
                    logger.info(f"✅ تم إرسال فاتورة السحب (TLS) إلى: {to_email}")

        except Exception as e:
            logger.error(f"⚠️ فشل إرسال فاتورة السحب إلى {to_email}: {e}")

    # إرسال في thread منفصل لعدم تأخير الاستجابة
    threading.Thread(target=_send, daemon=True).start()
