import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

cursor.execute('SHOW TABLES')
all_t = [r[0] for r in cursor.fetchall()]

matches = []
for t in all_t:
    try:
        cursor.execute(f"DESCRIBE {t}")
        cols = [r[0] for r in cursor.fetchall()]
        dcols = [c for c in cols if 'date' in c or 'created_at' in c]
        for dc in dcols:
            try:
                cursor.execute(f"SELECT count(*) FROM {t} WHERE {dc} >= '2026-09-01' AND {dc} <= '2026-09-30 23:59:59'")
                cnt = cursor.fetchone()[0]
                if cnt == 377:
                    matches.append((t, dc, cnt))
                    print(f"FOUND MATCH: {t}.{dc} = {cnt}")
            except:
                pass
    except:
        pass

print("Done. Total matches:", len(matches))
