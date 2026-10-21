import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            COUNT(1) as total_invoices,
            -- Bill Amounts
            SUM(mpi.sell_price) as total_bill_with_gst,
            SUM(mpi.sell_price_without_gst) as total_bill_without_gst,
            SUM(mpi.sell_gst_amount) as total_gst,

            -- Pharmacy Collection Total (Collected)
            SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) as coll_total,
            -- Collection Without GST (Scaled by sell_price_without_gst / sell_price)
            SUM(
                CASE 
                    WHEN mpi.sell_price > 0 
                    THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                END
            ) as coll_without_gst,

            -- IVF Collection Without GST
            SUM(
                CASE 
                    WHEN LOWER(c.name) LIKE '%ivf%' THEN 
                        CASE WHEN mpi.sell_price > 0 
                             THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                             ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                        END
                    ELSE 0 
                END
            ) as ivf_coll_without_gst,
            SUM(CASE WHEN LOWER(c.name) LIKE '%ivf%' THEN mpi.sell_price_without_gst ELSE 0 END) as ivf_bill_without_gst,

            -- INF Collection Without GST
            SUM(
                CASE 
                    WHEN LOWER(c.name) LIKE '%inf%' THEN 
                        CASE WHEN mpi.sell_price > 0 
                             THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                             ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                        END
                    ELSE 0 
                END
            ) as inf_coll_without_gst,
            SUM(CASE WHEN LOWER(c.name) LIKE '%inf%' THEN mpi.sell_price_without_gst ELSE 0 END) as inf_bill_without_gst,

            -- IUI Collection Without GST
            SUM(
                CASE 
                    WHEN LOWER(c.name) LIKE '%iui%' THEN 
                        CASE WHEN mpi.sell_price > 0 
                             THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                             ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                        END
                    ELSE 0 
                END
            ) as iui_coll_without_gst,
            SUM(CASE WHEN LOWER(c.name) LIKE '%iui%' THEN mpi.sell_price_without_gst ELSE 0 END) as iui_bill_without_gst,

            -- ANC Collection Without GST
            SUM(
                CASE 
                    WHEN LOWER(c.name) LIKE '%anc%' THEN 
                        CASE WHEN mpi.sell_price > 0 
                             THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                             ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                        END
                    ELSE 0 
                END
            ) as anc_coll_without_gst,
            SUM(CASE WHEN LOWER(c.name) LIKE '%anc%' THEN mpi.sell_price_without_gst ELSE 0 END) as anc_bill_without_gst,

            -- GYNEC Collection Without GST
            SUM(
                CASE 
                    WHEN LOWER(c.name) LIKE '%gynec%' THEN 
                        CASE WHEN mpi.sell_price > 0 
                             THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                             ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
                        END
                    ELSE 0 
                END
            ) as gynec_coll_without_gst,
            SUM(CASE WHEN LOWER(c.name) LIKE '%gynec%' THEN mpi.sell_price_without_gst ELSE 0 END) as gynec_bill_without_gst

        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        WHERE mpi.is_deleted = 0
    """)
    res = c.fetchone()
    print("Without GST figures:")
    print("Total Bill without GST:", res[2])
    print("Total Coll without GST:", res[5])
    print("IVF Coll without GST:", res[6])
    print("INF Coll without GST:", res[8])
    print("IUI Coll without GST:", res[10])
    print("ANC Coll without GST:", res[12])
    print("GYNEC Coll without GST:", res[14])
