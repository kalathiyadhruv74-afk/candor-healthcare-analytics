import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()
from django.db import connection
cursor = connection.cursor()

queries = [
    ("SELECT count(*) FROM patients_category WHERE created_at >= '2026-09-01' AND created_at <= '2026-09-30'", "patients_category created in Sept"),
    ("SELECT count(DISTINCT patients_id) FROM patients_category WHERE created_at >= '2026-09-01' AND created_at <= '2026-09-30'", "distinct patients_category in Sept"),
    ("SELECT count(*) FROM patients_category WHERE created_at >= '2026-09-01' AND created_at <= '2026-09-30' AND category_id IN (1,3,5,17)", "patients_category (1,3,5,17) in Sept"),
    ("SELECT count(DISTINCT patients_id) FROM patients_category WHERE created_at >= '2026-09-01' AND created_at <= '2026-09-30' AND category_id IN (1,3,5,17)", "distinct patients_category (1,3,5,17) in Sept"),
    ("SELECT count(*) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND is_done = 1 AND category_id IN (1,3,5,17)", "appts is_done=1 (1,3,5,17)"),
    ("SELECT count(DISTINCT patients_id) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND is_done = 1 AND category_id IN (1,3,5,17)", "distinct appts is_done=1 (1,3,5,17)"),
    ("SELECT count(*) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND is_done = 1 AND category_id IN (1,3,5,17) AND deleted_at IS NULL", "appts is_done=1 deleted_at null"),
    ("SELECT count(DISTINCT patients_id) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND is_done = 1 AND category_id IN (1,3,5,17) AND deleted_at IS NULL", "distinct appts is_done=1 deleted_at null"),
    ("SELECT count(*) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND category_id IN (1,3,5,17) AND deleted_at IS NULL", "appts deleted_at null (1,3,5,17)"),
    ("SELECT count(DISTINCT patients_id) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND category_id IN (1,3,5,17) AND deleted_at IS NULL", "distinct appts deleted_at null (1,3,5,17)"),
    ("SELECT count(*) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND approve_appointment = 1 AND category_id IN (1,3,5,17)", "approve_appointment=1 (1,3,5,17)"),
    ("SELECT count(DISTINCT patients_id) FROM appointments WHERE date >= '2026-09-01' AND date <= '2026-09-30' AND approve_appointment = 1 AND category_id IN (1,3,5,17)", "distinct approve_appointment=1 (1,3,5,17)"),
    ("SELECT count(*) FROM patients WHERE created_at >= '2026-09-01' AND created_at <= '2026-09-30' AND is_approved = 1", "patients approved in Sept"),
    ("SELECT count(*) FROM (SELECT patients_id, MIN(date) as fd FROM appointments WHERE category_id IN (1,3,5,17) GROUP BY patients_id) t WHERE fd >= '2026-09-01' AND fd <= '2026-09-30'", "First category appointment in Sept"),
    ("SELECT count(*) FROM (SELECT patients_id, MIN(date) as fd FROM appointments GROUP BY patients_id) t WHERE fd >= '2026-09-01' AND fd <= '2026-09-30' AND patients_id IN (SELECT id FROM patients WHERE created_at >= '2026-09-01')", "First appt in Sept for new patients"),
]

for q, label in queries:
    cursor.execute(q)
    cnt = cursor.fetchone()[0]
    print(f"{label}: {cnt}")
    if cnt == 377:
        print(f"!!! FOUND EXACT MATCH 377: {label} -> {q}")
