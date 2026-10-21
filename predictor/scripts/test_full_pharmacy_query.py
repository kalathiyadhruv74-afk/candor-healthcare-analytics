import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

kpi_query = """
    SELECT 
        COUNT(DISTINCT mpi.id) as total_invoices,
        COALESCE(SUM(mpi.sell_price), 0) as total_bill_amount,
        COALESCE(SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft), 0) as total_pharmacy_collection,
        COALESCE(SUM(mph.payment_cash), 0) as total_cash,
        COALESCE(SUM(mph.payment_upi), 0) as total_upi,
        COALESCE(SUM(mph.payment_cheque), 0) as total_cheque,
        COALESCE(SUM(mph.payment_neft), 0) as total_neft,
        
        -- IVF Medicine Income
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%ivf%' THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) ELSE 0 END), 0) as ivf_collection,
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%ivf%' THEN mpi.sell_price ELSE 0 END), 0) as ivf_bill,
        COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%ivf%' THEN mpi.id ELSE NULL END) as ivf_invoices,

        -- INF Medicine Income
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%inf%' THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) ELSE 0 END), 0) as inf_collection,
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%inf%' THEN mpi.sell_price ELSE 0 END), 0) as inf_bill,
        COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%inf%' THEN mpi.id ELSE NULL END) as inf_invoices,

        -- IUI Medicine Income
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%iui%' THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) ELSE 0 END), 0) as iui_collection,
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%iui%' THEN mpi.sell_price ELSE 0 END), 0) as iui_bill,
        COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%iui%' THEN mpi.id ELSE NULL END) as iui_invoices,

        -- ANC Medicine Income
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%anc%' THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) ELSE 0 END), 0) as anc_collection,
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%anc%' THEN mpi.sell_price ELSE 0 END), 0) as anc_bill,
        COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%anc%' THEN mpi.id ELSE NULL END) as anc_invoices,

        -- GYNEC Medicine Income
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%gynec%' THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) ELSE 0 END), 0) as gynec_collection,
        COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%gynec%' THEN mpi.sell_price ELSE 0 END), 0) as gynec_bill,
        COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%gynec%' THEN mpi.id ELSE NULL END) as gynec_invoices
    FROM medication_patients_invoices mpi
    LEFT JOIN category c ON mpi.category_id = c.id
    LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
    WHERE mpi.is_deleted = 0
"""

with connection.cursor() as cursor:
    cursor.execute(kpi_query)
    kpis = cursor.fetchone()
    print("KPIs fetched successfully:")
    print("Total Pharmacy Collection:", kpis[2])
    print("IVF Medicine Income:", kpis[7])
    print("INF Medicine Income:", kpis[10])
    print("IUI Medicine Income:", kpis[13])
    print("ANC Medicine Income:", kpis[16])
    print("GYNEC Medicine Income:", kpis[19])
