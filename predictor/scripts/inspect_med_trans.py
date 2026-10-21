import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SHOW TABLES LIKE '%medication_transaction%'")
    print(c.fetchall())
    c.execute("DESCRIBE medication_transaction")
    for r in c.fetchall():
        print(r)
    c.execute("""
        SELECT mt.category_id, mc.name, COUNT(*)
        FROM medication_transaction mt
        LEFT JOIN medication_category mc ON mt.category_id = mc.id
        GROUP BY mt.category_id, mc.name
        LIMIT 15
    """)
    print("\nmedication_transaction category counts:")
    for r in c.fetchall():
        print(r)
