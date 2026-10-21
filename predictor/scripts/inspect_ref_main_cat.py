import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SHOW TABLES LIKE '%main_cat%'")
    print("Tables like main_cat:", c.fetchall())

    c.execute("SELECT * FROM reference_main_category")
    cols = [d[0] for d in c.description]
    print(cols)
    for r in c.fetchall():
        print(r)
