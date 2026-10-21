import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            COUNT(1) as total_invoices,
            -- Fully paid invoices
            SUM(CASE WHEN (COALESCE(mph_agg.total_paid, 0)) >= mpi.sell_price AND mpi.sell_price > 0 THEN 1 ELSE 0 END) as fully_paid_invoices,
            -- Partially paid
            SUM(CASE WHEN (COALESCE(mph_agg.total_paid, 0)) > 0 AND (COALESCE(mph_agg.total_paid, 0)) < mpi.sell_price THEN 1 ELSE 0 END) as partial_paid_invoices,
            -- Zero paid (Credit / Pending / IPD package adjusted / Mediclaim)
            SUM(CASE WHEN COALESCE(mph_agg.total_paid, 0) = 0 THEN 1 ELSE 0 END) as zero_paid_invoices,
            
            SUM(mpi.sell_price_without_gst) as total_billed_no_gst,
            SUM(CASE 
                WHEN mpi.sell_price > 0 
                THEN (COALESCE(mph_agg.total_paid, 0)) * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE COALESCE(mph_agg.total_paid, 0)
            END) as total_collected_no_gst
        FROM medication_patients_invoices mpi
        LEFT JOIN (
            SELECT 
                medication_patients_invoice_id,
                SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as total_paid
            FROM medication_payment_history
            GROUP BY medication_patients_invoice_id
        ) mph_agg ON mph_agg.medication_patients_invoice_id = mpi.id
        WHERE mpi.is_deleted = 0
    """)
    row = c.fetchone()
    print("Invoices analysis:")
    print("Total Invoices:", row[0])
    print("Fully Paid Invoices:", row[1])
    print("Partially Paid Invoices:", row[2])
    print("Zero Paid (Credit / IPD / Package / Outstanding):", row[3])
    print("Total Billed (Without GST):", row[4])
    print("Total Collected (Without GST):", row[5])
