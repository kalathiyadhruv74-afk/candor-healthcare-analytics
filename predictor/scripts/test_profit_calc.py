import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'candor_ai.settings')
django.setup()

from django.db import connection

with connection.cursor() as c:
    c.execute("""
        SELECT 
            COUNT(1),
            -- Total Sell
            SUM(mpi.sell_price) as sell_price,
            SUM(mpi.sell_price_without_gst) as sell_price_without_gst,
            -- Total Purchase
            SUM(mpi.purchase_price) as purchase_price,
            SUM(
                CASE 
                    WHEN mpi.reference_purchase_price_without_gst > 0 THEN mpi.reference_purchase_price_without_gst
                    ELSE mpi.purchase_price * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))
                END
            ) as purchase_price_without_gst,
            -- Profit on Sales
            SUM(mpi.sell_price - mpi.purchase_price) as profit_on_sales_gross,
            SUM(
                mpi.sell_price_without_gst - 
                CASE 
                    WHEN mpi.reference_purchase_price_without_gst > 0 THEN mpi.reference_purchase_price_without_gst
                    ELSE mpi.purchase_price * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))
                END
            ) as profit_on_sales_without_gst
        FROM medication_patients_invoices mpi
        WHERE mpi.is_deleted = 0
    """)
    row = c.fetchone()
    print("Sales and Profit Summary:")
    print("Sell Price Without GST:", row[2])
    print("Purchase Price Without GST:", row[4])
    print("Profit On Sales Without GST:", row[6])
    margin_pct = (row[6] / row[2] * 100) if row[2] else 0
    print(f"Profit Margin %: {margin_pct:.1f}%")
