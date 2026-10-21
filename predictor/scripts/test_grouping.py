import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            CASE 
                WHEN LOWER(c.name) LIKE '%ivf%' THEN 'IVF'
                WHEN LOWER(c.name) LIKE '%inf%' THEN 'INF'
                WHEN LOWER(c.name) LIKE '%iui%' THEN 'IUI'
                WHEN LOWER(c.name) LIKE '%anc%' THEN 'ANC'
                WHEN LOWER(c.name) LIKE '%gynec%' THEN 'GYNEC'
                ELSE 'OTHER'
            END as department_group,
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM(mpi.sell_price), 0) as total_sell_price,
            COALESCE(SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft), 0) as total_collection,
            COALESCE(SUM(mph.payment_cash), 0) as total_cash,
            COALESCE(SUM(mph.payment_upi), 0) as total_upi,
            COALESCE(SUM(mph.payment_cheque), 0) as total_cheque,
            COALESCE(SUM(mph.payment_neft), 0) as total_neft
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        WHERE mpi.is_deleted = 0
        GROUP BY department_group
        ORDER BY total_collection DESC
    """)
    print("Aggregate breakdown by Requested Categories:")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            MIN(date_of_transaction), MAX(date_of_transaction)
        FROM medication_patients_invoices
        WHERE is_deleted = 0
    """)
    print("\nDate range:", c.fetchall())

    c.execute("""
        SELECT 
            b.id, b.name, COUNT(mpi.id)
        FROM branches b
        LEFT JOIN medication_patients_invoices mpi ON mpi.branch_id = b.id AND mpi.is_deleted = 0
        GROUP BY b.id, b.name
    """)
    print("\nBranches breakdown:")
    for r in c.fetchall():
        print(r)
