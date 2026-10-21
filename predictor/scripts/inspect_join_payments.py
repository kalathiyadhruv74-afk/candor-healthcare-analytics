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
            COUNT(DISTINCT mph.id) as payment_count,
            COALESCE(SUM(mph.payment_cash), 0) as cash,
            COALESCE(SUM(mph.payment_upi), 0) as upi,
            COALESCE(SUM(mph.payment_cheque), 0) as cheque,
            COALESCE(SUM(mph.payment_neft), 0) as neft,
            COALESCE(SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft), 0) as total_collection
        FROM medication_payment_history mph
        JOIN medication_patients_invoices mpi ON mph.medication_patients_invoice_id = mpi.id
        LEFT JOIN category c ON mpi.category_id = c.id
        WHERE mpi.is_deleted = 0
        GROUP BY c.id, c.name
        ORDER BY total_collection DESC
    """)
    print("Collection joined with medication_patients_invoices:")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT COUNT(*), SUM(sell_price)
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    print("Total invoice sell_price:", c.fetchall())

    c.execute("""
        SELECT 
            SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as total_invoice_payments
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    print("Total in medication_patients_invoices payment columns:", c.fetchall())
