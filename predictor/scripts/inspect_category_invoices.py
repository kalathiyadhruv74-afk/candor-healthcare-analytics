import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            c.id, 
            c.name, 
            COUNT(m.id) as invoice_count, 
            COALESCE(SUM(m.sell_price), 0) as total_sell_price,
            COALESCE(SUM(m.payment_cash), 0) as total_cash,
            COALESCE(SUM(m.payment_upi), 0) as total_upi,
            COALESCE(SUM(m.payment_cheque), 0) as total_cheque,
            COALESCE(SUM(m.payment_neft), 0) as total_neft
        FROM category c
        LEFT JOIN medication_patients_invoices m ON m.category_id = c.id AND m.is_deleted = 0
        GROUP BY c.id, c.name
        HAVING invoice_count > 0
        ORDER BY invoice_count DESC
    """)
    print("Invoices grouped by category table (c.id, c.name):")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            category_id, 
            COUNT(id) as cnt, 
            SUM(sell_price) as total_sell
        FROM medication_patients_invoices
        WHERE is_deleted = 0 AND (category_id = 0 OR category_id IS NULL)
        GROUP BY category_id
    """)
    print("\nInvoices with category_id 0 or NULL:")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            payment_cash, payment_upi, payment_cheque, payment_neft, sell_price, 
            (COALESCE(payment_cash,0) + COALESCE(payment_upi,0) + COALESCE(payment_cheque,0) + COALESCE(payment_neft,0)) as total_paid
        FROM medication_patients_invoices
        WHERE is_deleted = 0
        LIMIT 10
    """)
    print("\nSample invoice payment values:")
    for r in c.fetchall():
        print(r)
