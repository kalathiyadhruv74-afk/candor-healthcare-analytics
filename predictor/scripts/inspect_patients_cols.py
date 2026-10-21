import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("DESCRIBE patients")
    cols = [r[0] for r in c.fetchall()]
    print("patients columns:", cols)

    # Let's check patients category or if patients has category_id or similar
    cat_cols = [col for col in cols if 'cat' in col or 'type' in col]
    print("Category/type related cols in patients:", cat_cols)
    
    if 'category_id' in cols:
        c.execute("""
            SELECT 
                p.category_id,
                c.name,
                COUNT(mpi.id) as cnt,
                COALESCE(SUM(mpi.sell_price), 0) as sell_price,
                COALESCE(SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft), 0) as collected
            FROM medication_patients_invoices mpi
            LEFT JOIN patients p ON mpi.patients_id = p.id
            LEFT JOIN category c ON p.category_id = c.id
            LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
            WHERE mpi.category_id = 0 OR mpi.category_id IS NULL
            GROUP BY p.category_id, c.name
            ORDER BY cnt DESC
            LIMIT 10
        """)
        print("\nBreakdown of uncategorized mpi by patients.category_id:")
        for r in c.fetchall():
            print(r)
