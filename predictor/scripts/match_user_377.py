import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

# Check appointments where category_id is pure NEW clinical categories:
# User said:
# 50 iui Patients, 27 anc Patients, 35 ivf Patients, 48 gynec Patients = 160 in Varachha!
# And user listed branch counts:
# 160, 29, 16, 19, 0, 31, 0, 17, 19, 2, 0, 0, 17, 20, 4, 0, 0, 0, 19, 24
# Total = 377!

# Let's map user numbers to branches:
user_branch_counts = {
    2: 160,   # Varachha
    3: 29,    # Bharuch
    4: 16,    # Mahuva
    5: 19,    # Vesu
    6: 0,     # ParvatPatiya
    7: 31,    # KatarGam
    8: 0,     # Nandurbar
    9: 17,    # Amreli
    10: 19,   # Jamnagar
    11: 2,    # Vadodara
    12: 0,    # Veraval (or 1)
    13: 0,    # Goa
    14: 17,   # Surendranagar
    15: 20,   # Morbi
    16: 4,    # Bhavnagar
    17: 0,    # Vapi
    18: 0,    # Tulsi
    20: 0,    # ART bank
    21: 19,   # Gandhidham
    22: 24,   # Adajan
}
print("Branch mappings sum:", sum(user_branch_counts.values()))

# Let's see what appointment or patient query gives these exact numbers!
cursor.execute("""
SELECT 
    b.id,
    b.name,
    COUNT(DISTINCT a.patients_id) as distinct_patients,
    COUNT(a.id) as appts
FROM branch b
LEFT JOIN appointments a ON b.id = a.branch_id 
    AND a.date >= '2026-09-01' AND a.date <= '2026-09-28'
    AND a.category_id IN (1, 3, 5, 17)
    AND a.category_id NOT IN (11, 14, 22, 49, 50)
LEFT JOIN patients p ON a.patients_id = p.id
    AND (p.is_donor IS NULL OR p.is_donor = 0)
GROUP BY b.id, b.name
ORDER BY b.id;
""")
for r in cursor.fetchall():
    print(r[0], r[1], "-> distinct:", r[2], "total_appts:", r[3], "USER:", user_branch_counts.get(r[0], 0))
