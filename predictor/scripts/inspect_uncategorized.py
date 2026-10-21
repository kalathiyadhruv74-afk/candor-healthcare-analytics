import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            p.patient_type,
            COUNT(mpi.id) as cnt,
            SUM(mpi.sell_price) as sell_price,
            SUM(mpi.payment_cash + mpi.payment_upi + mpi.payment_cheque + mpi.payment_neft) as collected
        FROM medication_patients_invoices mpi
        LEFT JOIN patients p ON mpi.patients_id = p.id
        WHERE mpi.category_id = 0 OR mpi.category_id IS NULL
        GROUP BY p.patient_type
    """)
    print("category_id=0 breakdown by patient_type:")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            p.category_id,
            c.name,
            COUNT(mpi.id) as cnt,
            SUM(mpi.sell_price) as sell_price,
            SUM(mpi.payment_cash + mpi.payment_upi + mpi.payment_cheque + mpi.payment_neft) as collected
        FROM medication_patients_invoices mpi
        LEFT JOIN patients p ON mpi.patients_id = p.id
        LEFT JOIN category c ON p.category_id = c.id
        WHERE mpi.category_id = 0 OR mpi.category_id IS NULL
        GROUP BY p.category_id, c.name
        ORDER BY cnt DESC
        LIMIT 10
    """)
    print("\ncategory_id=0 breakdown by patients.category_id:")
    for r in c.fetchall():
        print(r)
