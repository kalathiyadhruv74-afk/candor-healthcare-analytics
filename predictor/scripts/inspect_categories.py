import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SELECT id, department_id, name FROM medication_category")
    print("medication_category rows:")
    for r in c.fetchall():
        print(r)
        
    c.execute("SELECT id, name FROM category")
    print("\ncategory rows:")
    for r in c.fetchall():
        print(r)
        
    c.execute("SELECT id, name FROM patients_category")
    print("\npatients_category rows:")
    for r in c.fetchall():
        print(r)
