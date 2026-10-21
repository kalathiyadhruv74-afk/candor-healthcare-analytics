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
            SUM(purchase_price),
            SUM(reference_purchase_price_without_gst),
            SUM(sell_price - purchase_price) as gross_profit,
            SUM(sell_price_without_gst - reference_purchase_price_without_gst) as net_profit_without_gst
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    row = c.fetchone()
    print("Profit check in medication_patients_invoices:")
    print("Count:", row[0])
    print("sell_price:", row[1])
    print("sell_price_without_gst:", row[2])
    print("purchase_price:", row[3])
    print("reference_purchase_price_without_gst:", row[4])
    print("Gross profit (with GST):", row[5])
    print("Net profit (without GST):", row[6])

    c.execute("""
        SELECT 
            id, invoice_no, sell_price, sell_price_without_gst, purchase_price, reference_purchase_price_without_gst,
            (sell_price - purchase_price) as profit_gross,
            (sell_price_without_gst - reference_purchase_price_without_gst) as profit_net
        FROM medication_patients_invoices
        WHERE is_deleted = 0 AND purchase_price > 0
        LIMIT 5
    """)
    print("\nSample purchase vs sell rows:")
    for r in c.fetchall():
        print(r)
