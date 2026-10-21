import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SHOW TABLES LIKE '%patient%category%'")
    print("Patient category tables:", c.fetchall())

    c.execute("SHOW TABLES LIKE '%appoint%'")
    print("Appointment tables:", c.fetchall())

    # Let's see if patients has an appointment or lead with category
    c.execute("""
        SELECT 
            mpi.id, mpi.patients_id, mpi.patients_name, mpi.category_id, mpi.date_of_transaction, mpi.sell_price
        FROM medication_patients_invoices mpi
        WHERE mpi.category_id = 0
        LIMIT 10
    """)
    print("\nSample category_id=0 invoices:")
    for r in c.fetchall():
        print(r)
