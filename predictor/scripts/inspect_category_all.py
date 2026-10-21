import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            c.id, c.name, COUNT(mpi.id) as cnt, SUM(mpi.sell_price) as total_val
        FROM category c
        LEFT JOIN medication_patients_invoices mpi ON mpi.category_id = c.id AND mpi.is_deleted = 0
        GROUP BY c.id, c.name
        ORDER BY total_val DESC
    """)
    rows = c.fetchall()
    print("All category mapping:")
    for r in rows:
        if r[2] > 0:
            print(r)
