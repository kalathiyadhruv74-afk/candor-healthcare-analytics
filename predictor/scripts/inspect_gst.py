import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            COUNT(1),
            SUM(sell_price),
            SUM(sell_price_without_gst),
            SUM(sell_gst_amount)
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    print("Totals in medication_patients_invoices:")
    for r in c.fetchall():
        print("Count, sell_price, sell_price_without_gst, sell_gst_amount:", r)

    c.execute("""
        SELECT 
            id, invoice_no, sell_price, sell_price_without_gst, sell_gst_amount,
            payment_cash, payment_upi
        FROM medication_patients_invoices
        WHERE is_deleted = 0 AND sell_price > 0
        LIMIT 5
    """)
    print("\nSample rows:")
    for r in c.fetchall():
        print(r)
