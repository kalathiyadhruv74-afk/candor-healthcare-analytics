import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SELECT COUNT(*), SUM(payment_cash), SUM(payment_upi), SUM(payment_cheque), SUM(payment_neft) FROM medication_payment_history")
    print("medication_payment_history totals:", c.fetchall())

    c.execute("SELECT * FROM medication_payment_history LIMIT 5")
    cols = [d[0] for d in c.description]
    print(cols)
    for r in c.fetchall():
        print(r)

    c.execute("""
        SELECT 
            mph.department_id,
            COUNT(mph.id),
            SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) as total_collected
        FROM medication_payment_history mph
        GROUP BY mph.department_id
    """)
    print("\nmedication_payment_history by dept:")
    for r in c.fetchall():
        print(r)
