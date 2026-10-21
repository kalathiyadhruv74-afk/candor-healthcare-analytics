import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            b.id,
            b.name,
            COUNT(mpi.id) as total_invoices,
            COALESCE(SUM(mpi.sell_price), 0) as total_sell_price,
            COALESCE(SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft), 0) as total_collected,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%ivf%' THEN mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft ELSE 0 END), 0) as ivf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%inf%' THEN mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft ELSE 0 END), 0) as inf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%iui%' THEN mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft ELSE 0 END), 0) as iui_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%anc%' THEN mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft ELSE 0 END), 0) as anc_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%gynec%' THEN mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft ELSE 0 END), 0) as gynec_collection
        FROM branch b
        JOIN medication_patients_invoices mpi ON mpi.branch_id = b.id AND mpi.is_deleted = 0
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        GROUP BY b.id, b.name
        ORDER BY total_collected DESC
    """)
    rows = c.fetchall()
    print("Branch breakdown (id, name, total_inv, total_sell, total_coll, IVF, INF, IUI, ANC, GYNEC):")
    for r in rows:
        print(r)
