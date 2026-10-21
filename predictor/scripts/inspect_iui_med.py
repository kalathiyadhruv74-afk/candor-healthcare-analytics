import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            c.id, c.name, COUNT(*)
        FROM category c
        WHERE LOWER(c.name) LIKE '%iui%'
        GROUP BY c.id, c.name
    """)
    print("Categories matching iui:", c.fetchall())

    c.execute("""
        SELECT 
            COUNT(*), SUM(sell_price)
        FROM medication_patients_invoices mpi
        JOIN category c ON mpi.category_id = c.id
        WHERE mpi.is_deleted = 0 AND (LOWER(c.name) LIKE '%iui%' OR LOWER(c.name) LIKE '%iui-h%')
    """)
    print("Invoices matching IUI:", c.fetchall())

    # Check department_id meaning in medication_category
    c.execute("""
        SELECT department_id, name, COUNT(*)
        FROM medication_category
        GROUP BY department_id, name
    """)
    print("medication_category departments:", c.fetchall())
