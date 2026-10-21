import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            mpi.id,
            mpi.invoice_no,
            mpi.date_of_transaction,
            mpi.patients_id,
            mpi.patients_name,
            c.name as category_name,
            mpi.sell_price,
            COALESCE(mph_agg.total_paid, 0) as total_collected,
            COALESCE(mph_agg.cash, 0) as cash,
            COALESCE(mph_agg.upi, 0) as upi,
            b.name as branch_name
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN branch b ON mpi.branch_id = b.id
        LEFT JOIN (
            SELECT 
                medication_patients_invoice_id,
                SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as total_paid,
                SUM(payment_cash) as cash,
                SUM(payment_upi) as upi
            FROM medication_payment_history
            GROUP BY medication_patients_invoice_id
        ) mph_agg ON mph_agg.medication_patients_invoice_id = mpi.id
        WHERE mpi.is_deleted = 0
        ORDER BY mpi.date_of_transaction DESC
        LIMIT 10
    """)
    cols = [d[0] for d in c.description]
    print(cols)
    for r in c.fetchall():
        print(r)
