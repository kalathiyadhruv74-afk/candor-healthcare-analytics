import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            p.main_category,
            COUNT(mpi.id) as cnt,
            COALESCE(SUM(mpi.sell_price), 0) as sell_price
        FROM medication_patients_invoices mpi
        LEFT JOIN patients p ON mpi.patients_id = p.id
        WHERE mpi.category_id = 0 OR mpi.category_id IS NULL
        GROUP BY p.main_category
        ORDER BY cnt DESC
    """)
    print("Uncategorized mpi by patients.main_category:")
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            p.main_category,
            COUNT(mpi.id) as cnt
        FROM medication_patients_invoices mpi
        LEFT JOIN patients p ON mpi.patients_id = p.id
        GROUP BY p.main_category
        ORDER BY cnt DESC
    """)
    print("\nAll mpi by patients.main_category:")
    for r in c.fetchall():
        print(r)
