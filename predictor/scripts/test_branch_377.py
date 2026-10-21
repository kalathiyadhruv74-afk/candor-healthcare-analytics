import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

# User's branch numbers:
# 377 total:
# 160: Varachha (2)
# 29: Bharuch (3) or KatarGam?
# Let's test various queries for September 1 to 28 2026:
# Exclude:
# - category_id IN (11, 14, 22, 49, 50) -- donor and stitches
# - patients.is_donor = 1
# - root_donor_id IS NOT NULL

# Let's check patients registered in Sept 1-28:
cursor.execute("""
SELECT 
    b.id,
    b.name,
    COUNT(p.id)
FROM branch b
LEFT JOIN patients p ON b.id = p.branch_id 
    AND p.created_at >= '2026-09-01' AND p.created_at <= '2026-09-28 23:59:59'
    AND (p.is_donor IS NULL OR p.is_donor = 0)
    AND (p.root_donor_id IS NULL OR p.root_donor_id = 0)
GROUP BY b.id, b.name
ORDER BY b.id;
""")
print("Patients created_at per branch (excluding donor):")
for r in cursor.fetchall():
    print(r)
