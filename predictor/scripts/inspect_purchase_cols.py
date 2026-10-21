import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            COUNT(1),
            COUNT(CASE WHEN purchase_price > 0 THEN 1 END) as has_purchase_price,
            COUNT(CASE WHEN reference_purchase_price_without_gst > 0 THEN 1 END) as has_ref_purchase_price,
            SUM(purchase_price),
            SUM(reference_purchase_price_without_gst)
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    print("Non-zero check:", c.fetchall())

    c.execute("""
        SELECT 
            id, date_of_transaction, purchase_price, reference_purchase_price_without_gst, sell_price, sell_price_without_gst
        FROM medication_patients_invoices
        WHERE is_deleted = 0 AND reference_purchase_price_without_gst > 0
        LIMIT 5
    """)
    print("\nRows where reference_purchase_price_without_gst > 0:")
    for r in c.fetchall():
        print(r)
        
    c.execute("""
        SELECT 
            id, date_of_transaction, purchase_price, reference_purchase_price_without_gst, sell_price, sell_price_without_gst
        FROM medication_patients_invoices
        WHERE is_deleted = 0 AND reference_purchase_price_without_gst = 0 AND purchase_price > 0
        LIMIT 5
    """)
    print("\nRows where reference_purchase_price_without_gst = 0 but purchase_price > 0:")
    for r in c.fetchall():
        print(r)
