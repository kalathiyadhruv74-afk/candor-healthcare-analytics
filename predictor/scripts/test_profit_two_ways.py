import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            -- Profit on Sales (Without GST)
            SUM(
                mpi.sell_price_without_gst - 
                CASE 
                    WHEN mpi.reference_purchase_price_without_gst > 0 THEN mpi.reference_purchase_price_without_gst
                    ELSE mpi.purchase_price * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))
                END
            ) as profit_on_sales_no_gst,

            -- Profit on Actual Collections (Without GST)
            SUM(
                CASE 
                    WHEN mpi.sell_price > 0 
                    THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * 
                         ((mpi.sell_price_without_gst - 
                           CASE 
                               WHEN mpi.reference_purchase_price_without_gst > 0 THEN mpi.reference_purchase_price_without_gst
                               ELSE mpi.purchase_price * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))
                           END) / mpi.sell_price)
                    ELSE 0
                END
            ) as profit_on_collected_no_gst,

            -- Total Collections Without GST
            SUM(
                CASE 
                    WHEN mpi.sell_price > 0 
                    THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                END
            ) as total_collected_no_gst
        FROM medication_patients_invoices mpi
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        WHERE mpi.is_deleted = 0
    """)
    r = c.fetchone()
    print("Profit comparisons:")
    print("Profit on Total Sales (Without GST):", r[0])
    print("Profit on Actual Collections (Without GST):", r[1])
    print("Total Collected (Without GST):", r[2])
