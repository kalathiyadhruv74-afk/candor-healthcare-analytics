import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

tables = ['ivf', 'iui', 'anc', 'gynec', 'anc_history', 'iui_history', 'ivf_history', 'patients_category', 'all_doctor_visits']

for t in tables:
    cursor.execute(f"DESCRIBE {t}")
    cols = [r[0] for r in cursor.fetchall()]
    b_col = 'branch_id' if 'branch_id' in cols else ('branch' if 'branch' in cols else None)
    d_col = 'created_at' if 'created_at' in cols else ('date' if 'date' in cols else None)
    if d_col:
        q1 = f"SELECT COUNT(*) FROM {t} WHERE {d_col} >= '2026-09-01' AND {d_col} <= '2026-09-28 23:59:59'"
        cursor.execute(q1)
        tot = cursor.fetchone()[0]
        v_tot = None
        if b_col:
            q2 = f"SELECT COUNT(*) FROM {t} WHERE {d_col} >= '2026-09-01' AND {d_col} <= '2026-09-28 23:59:59' AND {b_col} = '2'"
            cursor.execute(q2)
            v_tot = cursor.fetchone()[0]
        print(f"{t}: total={tot}, Varachha={v_tot}")
