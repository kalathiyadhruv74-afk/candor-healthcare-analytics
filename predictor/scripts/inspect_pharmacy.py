import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("SHOW TABLES")
    all_tables = [r[0] for r in c.fetchall()]
    dept_tables = [t for t in all_tables if 'dept' in t.lower() or 'department' in t.lower()]
    print("Dept tables:", dept_tables)
    
    cat_tables = [t for t in all_tables if 'cat' in t.lower()]
    print("Cat tables:", cat_tables)
    
    c.execute("SELECT department_id, COUNT(1), SUM(sell_price) FROM medication_patients_invoices WHERE is_deleted=0 GROUP BY department_id")
    print("Department_id summary in medication_patients_invoices:")
    for row in c.fetchall():
        print(row)
        
    c.execute("SELECT category_id, COUNT(1), SUM(sell_price) FROM medication_patients_invoices WHERE is_deleted=0 GROUP BY category_id")
    print("Category_id summary in medication_patients_invoices:")
    for row in c.fetchall():
        print(row)

    for ct in ['departments', 'department', 'medication_category', 'medication_predefined_category']:
        if ct in all_tables:
            c.execute(f"SELECT * FROM {ct} LIMIT 5")
            cols = [d[0] for d in c.description]
            print(f"Table {ct} ({cols}):")
            for r in c.fetchall():
                print(r)
