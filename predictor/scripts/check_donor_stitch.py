import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

cursor.execute("SELECT id, name FROM category WHERE name LIKE '%donor%' OR name LIKE '%stich%' OR name LIKE '%stitch%' OR name LIKE '%ivf-d%' OR name LIKE '%ivf - d%' OR id IN (11, 14, 22, 50)")
print("Donor/Stitch category rows:", cursor.fetchall())

cursor.execute("SELECT is_donor, COUNT(*) FROM patients GROUP BY is_donor")
print("patients.is_donor:", cursor.fetchall())
