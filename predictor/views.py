import json
import math
import os
import pymysql
import pandas as pd
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import PredictionLog
from .ml.model_engine import get_iui_predictor, get_ivf_predictor, sanitize_for_json

def root_redirect(request):
    return redirect("iui_page")

def iui_page(request):
    return render(request, "predictor/iui.html")

def ivf_page(request):
    return render(request, "predictor/ivf.html")

def anc_journey_page(request):
    return render(request, "predictor/anc_journey.html")

def opd_prediction_page(request):
    return render(request, "predictor/opd_prediction.html")

def ivf_booking_report_page(request):
    return render(request, "predictor/ivf_booking_report.html")

def pharmacy_report_page(request):
    return render(request, "predictor/pharmacy_report.html")

def collection_report_page(request):
    return render(request, "predictor/collection_report.html")

def ivf_booking_analytics_api(request):
    """
    Live API for IVF Booking Report:
    - total number of ivf booking with source of ivf booking
    - number of new ivf booking with source of ivf booking
    - number of 2nd pick up booking
    - lab use booking
    Includes date range and branch filters, monthly trends, and patient level details.
    """
    from django.db import connection
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    source_filter = request.GET.get("source", "").strip()

    where_clauses = ["1=1"]
    params = []

    if start_date:
        where_clauses.append("ip.date >= %s")
        params.append(start_date)
    if end_date:
        where_clauses.append("ip.date <= %s")
        params.append(end_date)
    if branch_id:
        where_clauses.append("ip.branch_id = %s")
        params.append(branch_id)

    where_sql = " AND ".join(where_clauses)

    cursor = connection.cursor()

    # Query 1: Source Breakdown
    source_query = f"""
        SELECT 
            COALESCE(rmc.category_name, 'Direct / Walk-in') as source_name,
            count(*) as total_bookings,
            SUM(CASE WHEN ip.cycle_no = 1 THEN 1 ELSE 0 END) as new_ivf_bookings,
            SUM(CASE WHEN (ip.cycle_no >= 2 AND ip.cycle_type = 'PickUp') 
                          OR LOWER(ip.remark) LIKE '%%2nd pick%%' 
                          OR LOWER(ip.remark) LIKE '%%re-pick%%' 
                          OR LOWER(ip.remark) LIKE '%%re pick%%' 
                          OR ip.cycle_no = 2 THEN 1 ELSE 0 END) as second_pickup_bookings,
            SUM(CASE WHEN LOWER(ip.remark) LIKE '%%lab use%%' 
                          OR LOWER(ip.remark) LIKE '%%lab charge%%' 
                          OR LOWER(ip.remark) LIKE '%%lab only%%' 
                          OR LOWER(ip.remark) LIKE '%%only lab%%' THEN 1 ELSE 0 END) as lab_use_bookings
        FROM ivf_payment ip
        JOIN patients p ON ip.patients_id = p.id
        LEFT JOIN reference_main_category rmc ON p.main_category = rmc.id
        WHERE {where_sql}
        GROUP BY source_name
        ORDER BY total_bookings DESC
    """
    cursor.execute(source_query, params)
    source_rows = cursor.fetchall()

    by_source = []
    total_all_bookings = 0
    total_new_ivf = 0
    total_second_pickup = 0
    total_lab_use = 0

    for r in source_rows:
        s_name = r[0] or "Direct / Walk-in"
        tot = int(r[1] or 0)
        new_cnt = int(r[2] or 0)
        sec_cnt = int(r[3] or 0)
        lab_cnt = int(r[4] or 0)

        total_all_bookings += tot
        total_new_ivf += new_cnt
        total_second_pickup += sec_cnt
        total_lab_use += lab_cnt

        by_source.append({
            "source": s_name,
            "total_bookings": tot,
            "new_ivf_bookings": new_cnt,
            "second_pickup_bookings": sec_cnt,
            "lab_use_bookings": lab_cnt,
            "new_percentage": round((new_cnt / tot * 100), 1) if tot > 0 else 0
        })

    # Query 2: Monthly Trends
    monthly_query = f"""
        SELECT 
            DATE_FORMAT(ip.date, '%%Y-%%m') as month_str,
            count(*) as total_bookings,
            SUM(CASE WHEN ip.cycle_no = 1 THEN 1 ELSE 0 END) as new_ivf_bookings,
            SUM(CASE WHEN (ip.cycle_no >= 2 AND ip.cycle_type = 'PickUp') 
                          OR LOWER(ip.remark) LIKE '%%2nd pick%%' 
                          OR LOWER(ip.remark) LIKE '%%re-pick%%' 
                          OR LOWER(ip.remark) LIKE '%%re pick%%' 
                          OR ip.cycle_no = 2 THEN 1 ELSE 0 END) as second_pickup_bookings,
            SUM(CASE WHEN LOWER(ip.remark) LIKE '%%lab use%%' 
                          OR LOWER(ip.remark) LIKE '%%lab charge%%' 
                          OR LOWER(ip.remark) LIKE '%%lab only%%' 
                          OR LOWER(ip.remark) LIKE '%%only lab%%' THEN 1 ELSE 0 END) as lab_use_bookings
        FROM ivf_payment ip
        WHERE {where_sql} AND ip.date IS NOT NULL
        GROUP BY month_str
        ORDER BY month_str ASC
    """
    cursor.execute(monthly_query, params)
    month_rows = cursor.fetchall()
    monthly_trend = []
    for mr in month_rows:
        monthly_trend.append({
            "month": mr[0],
            "total_bookings": int(mr[1] or 0),
            "new_ivf_bookings": int(mr[2] or 0),
            "second_pickup_bookings": int(mr[3] or 0),
            "lab_use_bookings": int(mr[4] or 0)
        })

    # Query 3: Patient booking details table (with optional source filter)
    detail_where = list(where_clauses)
    detail_params = list(params)
    if source_filter:
        if source_filter == "Direct / Walk-in":
            detail_where.append("rmc.category_name IS NULL")
        else:
            detail_where.append("rmc.category_name = %s")
            detail_params.append(source_filter)

    detail_where_sql = " AND ".join(detail_where)

    detail_query = f"""
        SELECT 
            ip.id,
            ip.patients_id,
            p.code,
            p.name,
            p.surname,
            p.mobile_number,
            COALESCE(b.name, CONCAT('Branch ', ip.branch_id)) as branch_name,
            COALESCE(rmc.category_name, 'Direct / Walk-in') as source_name,
            ip.date as booking_date,
            ip.cycle_no,
            ip.cycle_type,
            ip.package,
            ip.total_payment,
            ip.remark,
            CASE WHEN ip.cycle_no = 1 THEN 'New IVF' ELSE 'Repeat / Follow-up' END as ivf_category,
            CASE WHEN (ip.cycle_no >= 2 AND ip.cycle_type = 'PickUp') 
                      OR LOWER(ip.remark) LIKE '%%2nd pick%%' 
                      OR LOWER(ip.remark) LIKE '%%re-pick%%' 
                      OR LOWER(ip.remark) LIKE '%%re pick%%' 
                      OR ip.cycle_no = 2 THEN 'Yes' ELSE 'No' END as is_2nd_pickup,
            CASE WHEN LOWER(ip.remark) LIKE '%%lab use%%' 
                      OR LOWER(ip.remark) LIKE '%%lab charge%%' 
                      OR LOWER(ip.remark) LIKE '%%lab only%%' 
                      OR LOWER(ip.remark) LIKE '%%only lab%%' THEN 'Yes' ELSE 'No' END as is_lab_use
        FROM ivf_payment ip
        JOIN patients p ON ip.patients_id = p.id
        LEFT JOIN reference_main_category rmc ON p.main_category = rmc.id
        LEFT JOIN branch b ON ip.branch_id = b.id
        WHERE {detail_where_sql}
        ORDER BY ip.date DESC, ip.id DESC
        LIMIT 300
    """
    cursor.execute(detail_query, detail_params)
    records = []
    for row in cursor.fetchall():
        fname = row[3].strip() if row[3] else ""
        sname = row[4].strip() if row[4] else ""
        if sname and sname.lower() in fname.lower():
            patient_name = fname
        else:
            patient_name = f"{fname} {sname}".strip()

        records.append({
            "payment_id": row[0],
            "patient_id": row[1],
            "code": row[2] or "-",
            "patient_name": patient_name,
            "mobile": row[5] or "-",
            "branch_name": row[6] or "-",
            "source": row[7] or "Direct / Walk-in",
            "booking_date": row[8].strftime("%Y-%m-%d") if row[8] else "-",
            "cycle_no": row[9] if row[9] is not None else 1,
            "cycle_type": row[10] or "SELF",
            "package_amount": float(row[11]) if row[11] is not None else 0.0,
            "total_payment": float(row[12]) if row[12] is not None else 0.0,
            "remark": row[13] or "-",
            "ivf_category": row[14],
            "is_2nd_pickup": row[15],
            "is_lab_use": row[16]
        })

    # Available branches for dropdown
    cursor.execute("SELECT id, name FROM branch WHERE status = 1 OR id IN (SELECT DISTINCT branch_id FROM ivf_payment) ORDER BY name")
    branches = [{"id": b[0], "name": b[1]} for b in cursor.fetchall()]

    return JsonResponse({
        "status": "success",
        "summary": {
            "total_all_bookings": total_all_bookings,
            "total_new_ivf": total_new_ivf,
            "total_second_pickup": total_second_pickup,
            "total_lab_use": total_lab_use,
            "repeat_bookings": total_all_bookings - total_new_ivf,
            "new_ivf_percentage": round((total_new_ivf / total_all_bookings * 100), 1) if total_all_bookings > 0 else 0
        },
        "by_source": by_source,
        "monthly_trend": monthly_trend,
        "records": records,
        "branches": branches,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "source": source_filter
        }
    })

def pharmacy_analytics_api(request):
    """
    Live API for Pharmacy Collection & Medicine Income Analytics:
    - Total Pharmacy Collection (Cash, UPI, Cheque, NEFT)
    - IVF Medicine Income
    - INF Medicine Income
    - IUI Medicine Income
    - ANC Medicine Income
    - GYNEC Medicine Income
    - Other / Paediatric / Miscellaneous Medicine Income
    Includes:
    - Filters: start_date, end_date, branch_id, category_group, exclude_gst (without GST)
    - Monthly & Daily timeline trends
    - Branch-wise comparison
    - Payment mode breakdown (Cash vs UPI vs Cheque vs NEFT)
    - Detailed medication invoice ledger
    """
    from django.db import connection
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    category_group = request.GET.get("category_group", "").strip()
    exclude_gst = request.GET.get("exclude_gst", "1").lower() in ("1", "true", "yes")
    only_profit = request.GET.get("only_profit", "0").lower() in ("1", "true", "yes")

    where_clauses = ["mpi.is_deleted = 0"]
    params = []

    if start_date:
        where_clauses.append("mpi.date_of_transaction >= %s")
        params.append(start_date)
    if end_date:
        where_clauses.append("mpi.date_of_transaction <= %s")
        params.append(end_date)
    if branch_id:
        where_clauses.append("mpi.branch_id = %s")
        params.append(branch_id)

    where_sql = " AND ".join(where_clauses)
    cursor = connection.cursor()

    # Column / formula choices based on GST toggle & Profit toggle
    if exclude_gst:
        price_col = "mpi.sell_price_without_gst"
        # Pure purchase cost without GST
        purchase_cost = """
            (CASE 
                WHEN mpi.reference_purchase_price_without_gst > 0 THEN mpi.reference_purchase_price_without_gst
                ELSE mpi.purchase_price * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))
            END)
        """
        # Profit per invoice without GST
        profit_col = f"GREATEST(0, ({price_col} - {purchase_cost}))"
        
        # Collection scaled to net without GST
        paid_calc = """
            CASE 
                WHEN mpi.sell_price > 0 
                THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)
            END
        """
        cash_calc = """
            CASE 
                WHEN mpi.sell_price > 0 
                THEN mph.payment_cash * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE mph.payment_cash
            END
        """
        upi_calc = """
            CASE 
                WHEN mpi.sell_price > 0 
                THEN mph.payment_upi * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE mph.payment_upi
            END
        """
        cheque_calc = """
            CASE 
                WHEN mpi.sell_price > 0 
                THEN mph.payment_cheque * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE mph.payment_cheque
            END
        """
        neft_calc = """
            CASE 
                WHEN mpi.sell_price > 0 
                THEN mph.payment_neft * (mpi.sell_price_without_gst / mpi.sell_price)
                ELSE mph.payment_neft
            END
        """
        # Profit realized on collection (Margin % * Collection)
        profit_collected_calc = f"""
            CASE 
                WHEN mpi.sell_price > 0 
                THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * 
                     (({profit_col}) / mpi.sell_price)
                ELSE 0
            END
        """
    else:
        price_col = "mpi.sell_price"
        purchase_cost = "mpi.purchase_price"
        profit_col = f"GREATEST(0, (mpi.sell_price - mpi.purchase_price))"
        paid_calc = "(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft)"
        cash_calc = "mph.payment_cash"
        upi_calc = "mph.payment_upi"
        cheque_calc = "mph.payment_cheque"
        neft_calc = "mph.payment_neft"
        profit_collected_calc = f"""
            CASE 
                WHEN mpi.sell_price > 0 
                THEN (mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) * 
                     (({profit_col}) / mpi.sell_price)
                ELSE 0
            END
        """

    # If only_profit is ON, main display metric switches to net profit
    metric_collection = profit_collected_calc if only_profit else paid_calc
    metric_bill = profit_col if only_profit else price_col

    # Query 1: Overall KPIs and Categorical Income Breakdown
    kpi_query = f"""
        SELECT 
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({metric_bill}), 0) as total_bill_amount,
            COALESCE(SUM({metric_collection}), 0) as total_pharmacy_collection,
            COALESCE(SUM({cash_calc}), 0) as total_cash,
            COALESCE(SUM({upi_calc}), 0) as total_upi,
            COALESCE(SUM({cheque_calc}), 0) as total_cheque,
            COALESCE(SUM({neft_calc}), 0) as total_neft,
            
            -- IVF Medicine Income / Profit
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {metric_collection} ELSE 0 END), 0) as ivf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {metric_bill} ELSE 0 END), 0) as ivf_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN mpi.id ELSE NULL END) as ivf_invoices,

            -- INF Medicine Income / Profit
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {metric_collection} ELSE 0 END), 0) as inf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {metric_bill} ELSE 0 END), 0) as inf_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN mpi.id ELSE NULL END) as inf_invoices,

            -- IUI Medicine Income / Profit
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {metric_collection} ELSE 0 END), 0) as iui_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {metric_bill} ELSE 0 END), 0) as iui_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN mpi.id ELSE NULL END) as iui_invoices,

            -- ANC Medicine Income / Profit
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {metric_collection} ELSE 0 END), 0) as anc_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {metric_bill} ELSE 0 END), 0) as anc_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN mpi.id ELSE NULL END) as anc_invoices,

            -- GYNEC Medicine Income / Profit
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {metric_collection} ELSE 0 END), 0) as gynec_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {metric_bill} ELSE 0 END), 0) as gynec_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN mpi.id ELSE NULL END) as gynec_invoices,

            -- Other / General
            COALESCE(SUM(CASE WHEN c.name IS NULL 
                                   OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                       AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                       AND LOWER(c.name) NOT LIKE '%%gynec%%')
                              THEN {metric_collection} ELSE 0 END), 0) as other_collection,
            COALESCE(SUM(CASE WHEN c.name IS NULL 
                                   OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                       AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                       AND LOWER(c.name) NOT LIKE '%%gynec%%')
                              THEN {metric_bill} ELSE 0 END), 0) as other_bill,
            COUNT(DISTINCT CASE WHEN c.name IS NULL 
                                     OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                         AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                         AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                         AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                         AND LOWER(c.name) NOT LIKE '%%gynec%%')
                                THEN mpi.id ELSE NULL END) as other_invoices,
            
            -- Auxiliary Raw Totals for Margin Reference
            COALESCE(SUM({paid_calc}), 0) as raw_total_collection,
            COALESCE(SUM({price_col}), 0) as raw_total_bill,
            COALESCE(SUM({profit_collected_calc}), 0) as raw_profit_collected,
            COALESCE(SUM({profit_col}), 0) as raw_profit_billed
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        WHERE {where_sql}
    """
    cursor.execute(kpi_query, params)
    krow = cursor.fetchone()

    total_invoices = int(krow[0] or 0)
    total_bill_amount = float(krow[1] or 0.0)
    total_pharmacy_collection = float(krow[2] or 0.0)
    total_cash = float(krow[3] or 0.0)
    total_upi = float(krow[4] or 0.0)
    total_cheque = float(krow[5] or 0.0)
    total_neft = float(krow[6] or 0.0)

    ivf_income = float(krow[7] or 0.0)
    ivf_bill = float(krow[8] or 0.0)
    ivf_inv_cnt = int(krow[9] or 0)

    inf_income = float(krow[10] or 0.0)
    inf_bill = float(krow[11] or 0.0)
    inf_inv_cnt = int(krow[12] or 0)

    iui_income = float(krow[13] or 0.0)
    iui_bill = float(krow[14] or 0.0)
    iui_inv_cnt = int(krow[15] or 0)

    anc_income = float(krow[16] or 0.0)
    anc_bill = float(krow[17] or 0.0)
    anc_inv_cnt = int(krow[18] or 0)

    gynec_income = float(krow[19] or 0.0)
    gynec_bill = float(krow[20] or 0.0)
    gynec_inv_cnt = int(krow[21] or 0)

    other_income = float(krow[22] or 0.0)
    other_bill = float(krow[23] or 0.0)
    other_inv_cnt = int(krow[24] or 0)

    raw_total_collection = float(krow[25] or 0.0)
    raw_total_bill = float(krow[26] or 0.0)
    raw_profit_collected = float(krow[27] or 0.0)
    raw_profit_billed = float(krow[28] or 0.0)

    profit_margin_pct = round((raw_profit_collected / raw_total_collection * 100), 1) if raw_total_collection > 0 else 0.0

    # Categories list with percentage share
    prefix = "Net Profit" if only_profit else "Medicine Income"
    categories_breakdown = [
        {
            "key": "IVF",
            "name": f"IVF {prefix}",
            "collection": ivf_income,
            "bill_amount": ivf_bill,
            "invoices": ivf_inv_cnt,
            "pct": round((ivf_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#0284C7",
            "bg_color": "rgba(2, 132, 199, 0.12)",
            "icon": "🧬"
        },
        {
            "key": "ANC",
            "name": f"ANC {prefix}",
            "collection": anc_income,
            "bill_amount": anc_bill,
            "invoices": anc_inv_cnt,
            "pct": round((anc_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#10B981",
            "bg_color": "rgba(16, 185, 129, 0.12)",
            "icon": "👶"
        },
        {
            "key": "INF",
            "name": f"INF {prefix}",
            "collection": inf_income,
            "bill_amount": inf_bill,
            "invoices": inf_inv_cnt,
            "pct": round((inf_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#8B5CF6",
            "bg_color": "rgba(139, 92, 246, 0.12)",
            "icon": "💊"
        },
        {
            "key": "GYNEC",
            "name": f"GYNEC {prefix}",
            "collection": gynec_income,
            "bill_amount": gynec_bill,
            "invoices": gynec_inv_cnt,
            "pct": round((gynec_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#EC4899",
            "bg_color": "rgba(236, 72, 153, 0.12)",
            "icon": "🌸"
        },
        {
            "key": "IUI",
            "name": f"IUI {prefix}",
            "collection": iui_income,
            "bill_amount": iui_bill,
            "invoices": iui_inv_cnt,
            "pct": round((iui_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#F59E0B",
            "bg_color": "rgba(245, 158, 11, 0.12)",
            "icon": "🔬"
        },
        {
            "key": "OTHER",
            "name": f"Other {prefix}",
            "collection": other_income,
            "bill_amount": other_bill,
            "invoices": other_inv_cnt,
            "pct": round((other_income / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0,
            "color": "#64748B",
            "bg_color": "rgba(100, 116, 139, 0.12)",
            "icon": "🏥"
        }
    ]

    # Query 2: Monthly Timeline Trend
    monthly_query = f"""
        SELECT 
            DATE_FORMAT(mpi.date_of_transaction, '%%Y-%%m') as month_str,
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({metric_collection}), 0) as total_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {metric_collection} ELSE 0 END), 0) as ivf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {metric_collection} ELSE 0 END), 0) as inf_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {metric_collection} ELSE 0 END), 0) as iui_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {metric_collection} ELSE 0 END), 0) as anc_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {metric_collection} ELSE 0 END), 0) as gynec_collection
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        WHERE {where_sql} AND mpi.date_of_transaction IS NOT NULL
        GROUP BY month_str
        ORDER BY month_str ASC
    """
    cursor.execute(monthly_query, params)
    monthly_trend = []
    for mr in cursor.fetchall():
        monthly_trend.append({
            "month": mr[0],
            "invoices": int(mr[1] or 0),
            "total_collection": float(mr[2] or 0.0),
            "ivf_income": float(mr[3] or 0.0),
            "inf_income": float(mr[4] or 0.0),
            "iui_income": float(mr[5] or 0.0),
            "anc_income": float(mr[6] or 0.0),
            "gynec_income": float(mr[7] or 0.0)
        })

    # Query 3: Branch Breakdown
    branch_query = f"""
        SELECT 
            mpi.branch_id,
            COALESCE(b.name, CONCAT('Branch ', mpi.branch_id)) as branch_name,
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({metric_collection}), 0) as total_collection,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {metric_collection} ELSE 0 END), 0) as ivf_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {metric_collection} ELSE 0 END), 0) as inf_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {metric_collection} ELSE 0 END), 0) as iui_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {metric_collection} ELSE 0 END), 0) as anc_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {metric_collection} ELSE 0 END), 0) as gynec_income
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN medication_payment_history mph ON mph.medication_patients_invoice_id = mpi.id
        LEFT JOIN branch b ON mpi.branch_id = b.id
        WHERE {where_sql}
        GROUP BY mpi.branch_id, b.name
        ORDER BY total_collection DESC
    """
    cursor.execute(branch_query, params)
    branch_breakdown = []
    for br in cursor.fetchall():
        b_coll = float(br[3] or 0.0)
        branch_breakdown.append({
            "branch_id": br[0],
            "branch_name": br[1],
            "invoices": int(br[2] or 0),
            "total_collection": b_coll,
            "ivf_income": float(br[4] or 0.0),
            "inf_income": float(br[5] or 0.0),
            "iui_income": float(br[6] or 0.0),
            "anc_income": float(br[7] or 0.0),
            "gynec_income": float(br[8] or 0.0),
            "share_pct": round((b_coll / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0
        })

    # Query 4: Detailed Invoice Records (Filtered)
    detail_where = list(where_clauses)
    detail_params = list(params)
    if category_group:
        if category_group == "IVF":
            detail_where.append("LOWER(c.name) LIKE '%%ivf%%'")
        elif category_group == "INF":
            detail_where.append("LOWER(c.name) LIKE '%%inf%%'")
        elif category_group == "IUI":
            detail_where.append("LOWER(c.name) LIKE '%%iui%%'")
        elif category_group == "ANC":
            detail_where.append("LOWER(c.name) LIKE '%%anc%%'")
        elif category_group == "GYNEC":
            detail_where.append("LOWER(c.name) LIKE '%%gynec%%'")
        elif category_group == "OTHER":
            detail_where.append("(c.name IS NULL OR (LOWER(c.name) NOT LIKE '%%ivf%%' AND LOWER(c.name) NOT LIKE '%%inf%%' AND LOWER(c.name) NOT LIKE '%%iui%%' AND LOWER(c.name) NOT LIKE '%%anc%%' AND LOWER(c.name) NOT LIKE '%%gynec%%'))")

    detail_where_sql = " AND ".join(detail_where)

    detail_query = f"""
        SELECT 
            mpi.id,
            mpi.invoice_no,
            mpi.date_of_transaction,
            mpi.patients_id,
            COALESCE(p.code, '-') as patient_code,
            COALESCE(mpi.patients_name, p.name, 'Patient') as patient_name,
            COALESCE(b.name, CONCAT('Branch ', mpi.branch_id)) as branch_name,
            COALESCE(c.name, 'Uncategorized') as category_name,
            CASE 
                WHEN LOWER(c.name) LIKE '%%ivf%%' THEN 'IVF'
                WHEN LOWER(c.name) LIKE '%%inf%%' THEN 'INF'
                WHEN LOWER(c.name) LIKE '%%iui%%' THEN 'IUI'
                WHEN LOWER(c.name) LIKE '%%anc%%' THEN 'ANC'
                WHEN LOWER(c.name) LIKE '%%gynec%%' THEN 'GYNEC'
                ELSE 'OTHER'
            END as department_group,
            {metric_bill} as bill_amount,
            COALESCE(
                CASE 
                    WHEN {1 if exclude_gst else 0} = 1 AND mpi.sell_price > 0
                    THEN mph_agg.total_paid * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE mph_agg.total_paid
                END, 0
            ) as raw_collected,
            COALESCE(
                CASE 
                    WHEN {1 if exclude_gst else 0} = 1 AND mpi.sell_price > 0
                    THEN mph_agg.cash * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE mph_agg.cash
                END, 0
            ) as cash,
            COALESCE(
                CASE 
                    WHEN {1 if exclude_gst else 0} = 1 AND mpi.sell_price > 0
                    THEN mph_agg.upi * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE mph_agg.upi
                END, 0
            ) as upi,
            COALESCE(
                CASE 
                    WHEN {1 if exclude_gst else 0} = 1 AND mpi.sell_price > 0
                    THEN mph_agg.cheque * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE mph_agg.cheque
                END, 0
            ) as cheque,
            COALESCE(
                CASE 
                    WHEN {1 if exclude_gst else 0} = 1 AND mpi.sell_price > 0
                    THEN mph_agg.neft * (mpi.sell_price_without_gst / mpi.sell_price)
                    ELSE mph_agg.neft
                END, 0
            ) as neft,
            mpi.sell_gst_amount,
            {profit_col} as invoice_profit,
            COALESCE(
                CASE 
                    WHEN mpi.sell_price > 0 
                    THEN mph_agg.total_paid * (({profit_col}) / mpi.sell_price)
                    ELSE 0
                END, 0
            ) as collected_profit
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN patients p ON mpi.patients_id = p.id
        LEFT JOIN branch b ON mpi.branch_id = b.id
        LEFT JOIN (
            SELECT 
                medication_patients_invoice_id,
                SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as total_paid,
                SUM(payment_cash) as cash,
                SUM(payment_upi) as upi,
                SUM(payment_cheque) as cheque,
                SUM(payment_neft) as neft
            FROM medication_payment_history
            GROUP BY medication_patients_invoice_id
        ) mph_agg ON mph_agg.medication_patients_invoice_id = mpi.id
        WHERE {detail_where_sql}
        ORDER BY mpi.date_of_transaction DESC, mpi.id DESC
        LIMIT 300
    """
    cursor.execute(detail_query, detail_params)
    records = []
    for row in cursor.fetchall():
        bill_disp = float(row[9] or 0.0)
        coll_disp = float(row[17] if only_profit else row[10])
        records.append({
            "invoice_id": row[0],
            "invoice_no": row[1] or "-",
            "date": row[2].strftime("%Y-%m-%d") if row[2] else "-",
            "patient_id": row[3],
            "patient_code": row[4],
            "patient_name": row[5],
            "branch_name": row[6],
            "category_name": row[7],
            "department_group": row[8],
            "bill_amount": bill_disp,
            "collected": coll_disp,
            "cash": float(row[11] or 0.0),
            "upi": float(row[12] or 0.0),
            "cheque": float(row[13] or 0.0),
            "neft": float(row[14] or 0.0),
            "gst_amount": float(row[15] or 0.0),
            "net_profit": float(row[16] or 0.0),
            "collected_profit": float(row[17] or 0.0)
        })

    # Available branches for dropdown
    cursor.execute("SELECT id, name FROM branch WHERE status = 1 OR id IN (SELECT DISTINCT branch_id FROM medication_patients_invoices) ORDER BY name")
    branches = [{"id": b[0], "name": b[1]} for b in cursor.fetchall()]

    return JsonResponse({
        "status": "success",
        "exclude_gst": exclude_gst,
        "only_profit": only_profit,
        "summary": {
            "total_invoices": total_invoices,
            "total_bill_amount": total_bill_amount,
            "total_pharmacy_collection": total_pharmacy_collection,
            "ivf_medicine_income": ivf_income,
            "inf_medicine_income": inf_income,
            "iui_medicine_income": iui_income,
            "anc_medicine_income": anc_income,
            "gynec_medicine_income": gynec_income,
            "other_medicine_income": other_income,
            "raw_total_collection": raw_total_collection,
            "raw_total_bill": raw_total_bill,
            "raw_profit_collected": raw_profit_collected,
            "raw_profit_billed": raw_profit_billed,
            "profit_margin_pct": profit_margin_pct,
            "payment_modes": {
                "cash": total_cash,
                "upi": total_upi,
                "cheque": total_cheque,
                "neft": total_neft,
                "cash_pct": round((total_cash / raw_total_collection * 100), 1) if raw_total_collection > 0 else 0,
                "upi_pct": round((total_upi / raw_total_collection * 100), 1) if raw_total_collection > 0 else 0,
            }
        },
        "categories_breakdown": categories_breakdown,
        "monthly_trend": monthly_trend,
        "branch_breakdown": branch_breakdown,
        "records": records,
        "branches": branches,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "category_group": category_group,
            "exclude_gst": exclude_gst,
            "only_profit": only_profit
        }
    })

def collection_analytics_api(request):
    """
    Live API for Unified Collection & Payment Return Report:
    - Collection (Net Total = Healthcare Collection + Pharmacy Collection - Payment Return)
    - Total Collection (Gross Combined Collection)
    - Total Healthcare Collection (Indoor deposits / treatments)
    - Total Pharmacy Collection (Medication payments)
    - PAYMENT RETURN (Indoor refunds/returns + Pharmacy sales returns/credit notes)
    Supports date range filtering, branch filtering, monthly trends, payment mode breakdown, and granular transaction ledger.
    """
    from django.db import connection
    start_date = request.GET.get("start_date", "2026-01-01").strip()
    end_date = request.GET.get("end_date", "").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    source_filter = request.GET.get("source", "").strip().lower()  # all, healthcare, pharmacy, return

    cursor = connection.cursor()

    # --- 1. HEALTHCARE FILTERS ---
    hc_where = ["1=1"]
    hc_params = []
    if start_date:
        hc_where.append("DATE(d.created_at) >= %s")
        hc_params.append(start_date)
    if end_date:
        hc_where.append("DATE(d.created_at) <= %s")
        hc_params.append(end_date)
    if branch_id:
        hc_where.append("d.branch_id = %s")
        hc_params.append(branch_id)
    hc_where_sql = " AND ".join(hc_where)

    # --- 2. PHARMACY COLLECTION FILTERS ---
    ph_where = ["1=1"]
    ph_params = []
    if start_date:
        ph_where.append("DATE(mph.date_of_transaction) >= %s")
        ph_params.append(start_date)
    if end_date:
        ph_where.append("DATE(mph.date_of_transaction) <= %s")
        ph_params.append(end_date)
    if branch_id:
        ph_where.append("mph.branch_id = %s")
        ph_params.append(branch_id)
    ph_where_sql = " AND ".join(ph_where)

    # --- 3. PHARMACY RETURN FILTERS ---
    pr_where = ["1=1"]
    pr_params = []
    if start_date:
        pr_where.append("DATE(msc.date_of_transaction) >= %s")
        pr_params.append(start_date)
    if end_date:
        pr_where.append("DATE(msc.date_of_transaction) <= %s")
        pr_params.append(end_date)
    if branch_id:
        pr_where.append("msc.branch_id = %s")
        pr_params.append(branch_id)
    pr_where_sql = " AND ".join(pr_where)

    # --- EXECUTE HEALTHCARE AGGREGATE ---
    hc_sql = f"""
        SELECT 
            SUM(CASE WHEN d.case_type = 'Credit' THEN d.amount ELSE 0 END) as gross_credit,
            SUM(CASE WHEN d.case_type = 'Debit' THEN d.amount ELSE 0 END) as return_debit,
            COUNT(CASE WHEN d.case_type = 'Credit' THEN 1 END) as credit_count,
            COUNT(CASE WHEN d.case_type = 'Debit' THEN 1 END) as return_count,
            SUM(CASE WHEN d.case_type = 'Credit' AND d.payment_type = 2 THEN d.amount ELSE 0 END) as cash_amt,
            SUM(CASE WHEN d.case_type = 'Credit' AND d.payment_type = 4 THEN d.amount ELSE 0 END) as upi_amt,
            SUM(CASE WHEN d.case_type = 'Credit' AND d.payment_type = 3 THEN d.amount ELSE 0 END) as cheque_amt,
            SUM(CASE WHEN d.case_type = 'Credit' AND d.payment_type = 5 THEN d.amount ELSE 0 END) as neft_amt,
            SUM(CASE WHEN d.case_type = 'Credit' AND d.payment_type NOT IN (2, 3, 4, 5) THEN d.amount ELSE 0 END) as other_amt
        FROM indoor_deposits d
        WHERE {hc_where_sql}
    """
    cursor.execute(hc_sql, hc_params)
    hc_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0)
    hc_gross = float(hc_row[0] or 0.0)
    hc_return = float(hc_row[1] or 0.0)
    hc_credit_count = int(hc_row[2] or 0)
    hc_return_count = int(hc_row[3] or 0)
    hc_cash = float(hc_row[4] or 0.0)
    hc_upi = float(hc_row[5] or 0.0)
    hc_cheque = float(hc_row[6] or 0.0)
    hc_neft = float(hc_row[7] or 0.0)
    hc_other = float(hc_row[8] or 0.0)

    # --- EXECUTE PHARMACY COLLECTION AGGREGATE ---
    ph_sql = f"""
        SELECT 
            SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) as total_pharmacy,
            COUNT(*) as count_pharmacy,
            SUM(mph.payment_cash) as cash_amt,
            SUM(mph.payment_upi) as upi_amt,
            SUM(mph.payment_cheque) as cheque_amt,
            SUM(mph.payment_neft) as neft_amt
        FROM medication_payment_history mph
        WHERE {ph_where_sql}
    """
    cursor.execute(ph_sql, ph_params)
    ph_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0)
    ph_gross = float(ph_row[0] or 0.0)
    ph_count = int(ph_row[1] or 0)
    ph_cash = float(ph_row[2] or 0.0)
    ph_upi = float(ph_row[3] or 0.0)
    ph_cheque = float(ph_row[4] or 0.0)
    ph_neft = float(ph_row[5] or 0.0)

    # --- EXECUTE PHARMACY RETURN AGGREGATE ---
    pr_sql = f"""
        SELECT 
            SUM(msc.payment_cash + msc.payment_upi + msc.payment_cheque + msc.payment_neft) as total_return,
            COUNT(*) as count_return,
            SUM(msc.payment_cash) as cash_amt,
            SUM(msc.payment_upi) as upi_amt,
            SUM(msc.payment_cheque) as cheque_amt,
            SUM(msc.payment_neft) as neft_amt
        FROM medication_sales_credit msc
        WHERE {pr_where_sql}
    """
    cursor.execute(pr_sql, pr_params)
    pr_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0)
    pr_return = float(pr_row[0] or 0.0)
    pr_count = int(pr_row[1] or 0)
    pr_cash = float(pr_row[2] or 0.0)
    pr_upi = float(pr_row[3] or 0.0)
    pr_cheque = float(pr_row[4] or 0.0)
    pr_neft = float(pr_row[5] or 0.0)

    # --- CORE KPI METRICS REQUESTED BY USER ---
    # 1. Total Collection (Gross Combined Collection)
    total_gross_collection = round(hc_gross + ph_gross, 2)
    # 2. Total Healthcare Collection
    total_healthcare_collection = round(hc_gross, 2)
    # 3. Total Pharmacy Collection
    total_pharmacy_collection = round(ph_gross, 2)
    # 4. PAYMENT RETURN (Hospital Refund/Debit + Pharmacy Credit Note/Sales Return)
    total_payment_return = round(hc_return + pr_return, 2)
    # 5. Collection (Net Final In-Hand Collection)
    net_collection = round(total_gross_collection - total_payment_return, 2)

    # Payment modes summary (Net)
    total_cash_net = round((hc_cash + ph_cash) - (pr_cash), 2)
    total_upi_net = round((hc_upi + ph_upi) - (pr_upi), 2)
    total_cheque_net = round((hc_cheque + ph_cheque) - (pr_cheque), 2)
    total_neft_net = round((hc_neft + ph_neft) - (pr_neft), 2)
    total_other_net = round(hc_other, 2)

    # --- MONTHLY TRENDS ---
    # Monthly healthcare
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(d.created_at, '%%Y-%%m') as ym,
            SUM(CASE WHEN d.case_type = 'Credit' THEN d.amount ELSE 0 END) as gross_hc,
            SUM(CASE WHEN d.case_type = 'Debit' THEN d.amount ELSE 0 END) as return_hc
        FROM indoor_deposits d
        WHERE {hc_where_sql}
        GROUP BY ym
        ORDER BY ym ASC
    """, hc_params)
    hc_monthly = {r[0]: {"gross_hc": float(r[1] or 0), "return_hc": float(r[2] or 0)} for r in cursor.fetchall()}

    # Monthly pharmacy
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(mph.date_of_transaction, '%%Y-%%m') as ym,
            SUM(mph.payment_cash + mph.payment_upi + mph.payment_cheque + mph.payment_neft) as gross_ph
        FROM medication_payment_history mph
        WHERE {ph_where_sql}
        GROUP BY ym
        ORDER BY ym ASC
    """, ph_params)
    ph_monthly = {r[0]: float(r[1] or 0) for r in cursor.fetchall()}

    # Monthly pharmacy return
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(msc.date_of_transaction, '%%Y-%%m') as ym,
            SUM(msc.payment_cash + msc.payment_upi + msc.payment_cheque + msc.payment_neft) as return_ph
        FROM medication_sales_credit msc
        WHERE {pr_where_sql}
        GROUP BY ym
        ORDER BY ym ASC
    """, pr_params)
    pr_monthly = {r[0]: float(r[1] or 0) for r in cursor.fetchall()}

    all_months = sorted(list(set(list(hc_monthly.keys()) + list(ph_monthly.keys()) + list(pr_monthly.keys()))))
    monthly_trend = []
    for ym in all_months:
        ghc = hc_monthly.get(ym, {}).get("gross_hc", 0.0)
        rhc = hc_monthly.get(ym, {}).get("return_hc", 0.0)
        gph = ph_monthly.get(ym, 0.0)
        rph = pr_monthly.get(ym, 0.0)
        tot_gross = ghc + gph
        tot_ret = rhc + rph
        tot_net = tot_gross - tot_ret
        monthly_trend.append({
            "month": ym,
            "net_collection": round(tot_net, 2),
            "total_collection": round(tot_gross, 2),
            "healthcare_collection": round(ghc, 2),
            "pharmacy_collection": round(gph, 2),
            "payment_return": round(tot_ret, 2)
        })

    # --- BRANCH BREAKDOWN ---
    cursor.execute("""
        SELECT id, name FROM branch WHERE status = 1 OR id IN (SELECT DISTINCT branch_id FROM indoor_deposits) ORDER BY name
    """)
    all_branch_rows = cursor.fetchall()
    branches = [{"id": b[0], "name": b[1]} for b in all_branch_rows]

    # Branch aggregations
    branch_stats_sql = f"""
        SELECT 
            b.id,
            b.name,
            COALESCE(hc.gross_hc, 0) as gross_hc,
            COALESCE(hc.return_hc, 0) as return_hc,
            COALESCE(ph.gross_ph, 0) as gross_ph,
            COALESCE(pr.return_ph, 0) as return_ph
        FROM branch b
        LEFT JOIN (
            SELECT branch_id,
                   SUM(CASE WHEN case_type = 'Credit' THEN amount ELSE 0 END) as gross_hc,
                   SUM(CASE WHEN case_type = 'Debit' THEN amount ELSE 0 END) as return_hc
            FROM indoor_deposits d
            WHERE {hc_where_sql}
            GROUP BY branch_id
        ) hc ON hc.branch_id = b.id
        LEFT JOIN (
            SELECT branch_id,
                   SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as gross_ph
            FROM medication_payment_history mph
            WHERE {ph_where_sql}
            GROUP BY branch_id
        ) ph ON ph.branch_id = b.id
        LEFT JOIN (
            SELECT branch_id,
                   SUM(payment_cash + payment_upi + payment_cheque + payment_neft) as return_ph
            FROM medication_sales_credit msc
            WHERE {pr_where_sql}
            GROUP BY branch_id
        ) pr ON pr.branch_id = b.id
        HAVING (gross_hc > 0 OR gross_ph > 0 OR return_hc > 0 OR return_ph > 0)
        ORDER BY (gross_hc + gross_ph) DESC
    """
    combined_params = hc_params + ph_params + pr_params
    cursor.execute(branch_stats_sql, combined_params)
    branch_rows = cursor.fetchall()
    branch_breakdown = []
    for r in branch_rows:
        b_id, b_name, b_ghc, b_rhc, b_gph, b_rph = r[0], r[1], float(r[2] or 0), float(r[3] or 0), float(r[4] or 0), float(r[5] or 0)
        b_gross = b_ghc + b_gph
        b_ret = b_rhc + b_rph
        b_net = b_gross - b_ret
        branch_breakdown.append({
            "branch_id": b_id,
            "branch_name": b_name,
            "net_collection": round(b_net, 2),
            "total_collection": round(b_gross, 2),
            "healthcare_collection": round(b_ghc, 2),
            "pharmacy_collection": round(b_gph, 2),
            "payment_return": round(b_ret, 2),
            "pct_of_total": round((b_net / net_collection * 100), 1) if net_collection > 0 else 0
        })

    # --- RECENT TRANSACTIONS LEDGER (Up to 250 items) ---
    records = []
    
    # 1. Healthcare Credits & Debits
    hc_rec_query = f"""
        SELECT 
            d.id,
            d.created_at,
            'Healthcare' as source,
            d.case_type,
            d.amount,
            p.id as patient_id,
            p.code as patient_code,
            CONCAT(IFNULL(p.name, ''), ' ', IFNULL(p.surname, '')) as patient_name,
            IFNULL(b.name, CONCAT('Branch ', d.branch_id)) as branch_name,
            CASE d.payment_type
                WHEN 2 THEN 'Cash'
                WHEN 4 THEN 'UPI'
                WHEN 3 THEN 'Cheque'
                WHEN 5 THEN 'NEFT/RTGS'
                WHEN 1 THEN 'NetBanking'
                ELSE 'Other'
            END as mode_str,
            COALESCE(d.comment, d.remark, d.injection, '-') as reference_note
        FROM indoor_deposits d
        LEFT JOIN patients p ON d.patient_id = p.id
        LEFT JOIN branch b ON d.branch_id = b.id
        WHERE {hc_where_sql}
        ORDER BY d.created_at DESC
        LIMIT 150
    """
    cursor.execute(hc_rec_query, hc_params)
    for r in cursor.fetchall():
        is_ret = (str(r[3]).strip().lower() == "debit")
        records.append({
            "id": f"HC-{r[0]}",
            "date": r[1].strftime("%Y-%m-%d %H:%M") if r[1] else "-",
            "source": "Healthcare Collection" if not is_ret else "Healthcare Return",
            "source_type": "healthcare",
            "is_return": is_ret,
            "amount": float(r[4] or 0),
            "patient_id": r[5],
            "patient_code": r[6] or "-",
            "patient_name": (r[7] or "").strip() or "Walk-in Patient",
            "branch_name": r[8] or "-",
            "payment_mode": r[9] or "Cash",
            "reference": r[10] or "-"
        })

    # 2. Pharmacy Returns (Medication Sales Credit)
    pr_rec_query = f"""
        SELECT 
            msc.id,
            msc.date_of_transaction,
            'Pharmacy Return' as source,
            'Debit' as case_type,
            (msc.payment_cash + msc.payment_upi + msc.payment_cheque + msc.payment_neft) as amount,
            p.id as patient_id,
            p.code as patient_code,
            CONCAT(IFNULL(p.name, ''), ' ', IFNULL(p.surname, '')) as patient_name,
            IFNULL(b.name, CONCAT('Branch ', msc.branch_id)) as branch_name,
            CASE 
                WHEN msc.payment_upi > 0 THEN 'UPI'
                WHEN msc.payment_cash > 0 THEN 'Cash'
                WHEN msc.payment_cheque > 0 THEN 'Cheque'
                WHEN msc.payment_neft > 0 THEN 'NEFT'
                ELSE 'Cash'
            END as mode_str,
            CONCAT('Credit Note #', IFNULL(msc.credit_note_no, msc.id)) as reference_note
        FROM medication_sales_credit msc
        LEFT JOIN patients p ON msc.patients_id = p.id
        LEFT JOIN branch b ON msc.branch_id = b.id
        WHERE {pr_where_sql}
        ORDER BY msc.date_of_transaction DESC, msc.id DESC
        LIMIT 100
    """
    cursor.execute(pr_rec_query, pr_params)
    for r in cursor.fetchall():
        records.append({
            "id": f"PH-RET-{r[0]}",
            "date": r[1].strftime("%Y-%m-%d") if r[1] else "-",
            "source": "Pharmacy Return (Credit Note)",
            "source_type": "pharmacy_return",
            "is_return": True,
            "amount": float(r[4] or 0),
            "patient_id": r[5],
            "patient_code": r[6] or "-",
            "patient_name": (r[7] or "").strip() or "Pharmacy Customer",
            "branch_name": r[8] or "-",
            "payment_mode": r[9] or "Cash",
            "reference": r[10] or "-"
        })

    # Sort records descending by date
    records.sort(key=lambda x: x["date"], reverse=True)

    return JsonResponse({
        "status": "success",
        "summary": {
            "net_collection": net_collection,
            "total_collection": total_gross_collection,
            "total_healthcare_collection": total_healthcare_collection,
            "total_pharmacy_collection": total_pharmacy_collection,
            "payment_return": total_payment_return,
            "healthcare_return": round(hc_return, 2),
            "pharmacy_return": round(pr_return, 2),
            "transaction_counts": {
                "healthcare_credits": hc_credit_count,
                "healthcare_returns": hc_return_count,
                "pharmacy_payments": ph_count,
                "pharmacy_returns": pr_count,
                "total_transactions": hc_credit_count + hc_return_count + ph_count + pr_count
            },
            "payment_modes": {
                "cash": total_cash_net,
                "upi": total_upi_net,
                "cheque": total_cheque_net,
                "neft": total_neft_net,
                "other": total_other_net,
                "cash_pct": round((total_cash_net / net_collection * 100), 1) if net_collection > 0 else 0,
                "upi_pct": round((total_upi_net / net_collection * 100), 1) if net_collection > 0 else 0,
                "cheque_pct": round((total_cheque_net / net_collection * 100), 1) if net_collection > 0 else 0,
                "neft_pct": round((total_neft_net / net_collection * 100), 1) if net_collection > 0 else 0,
            }
        },
        "monthly_trend": monthly_trend,
        "branch_breakdown": branch_breakdown,
        "records": records[:200],
        "branches": branches,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "source": source_filter
        }
    })

def opd_prediction_api(request):
    from .ml.opd_prediction_engine import get_opd_prediction_data
    try:
        growth = float(request.GET.get("growth_rate", 0.035))
        digital_boost = float(request.GET.get("digital_boost", 0.08))
        attended_only = request.GET.get("attended_only", "false").lower() in ("true", "1", "yes")
        month = request.GET.get("month", "").strip() or None
        data = get_opd_prediction_data(growth_rate=growth, digital_boost=digital_boost, attended_only=attended_only, selected_month=month)
        return JsonResponse({"status": "success", "data": data})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
def sync_live_opd_api(request):
    from .ml.opd_prediction_engine import sync_candor_live_data, get_opd_prediction_data
    try:
        mobile = request.POST.get("mobile", "8320702976").strip() or "8320702976"
        otp = request.POST.get("otp", "5555").strip() or "5555"
        sync_result = sync_candor_live_data(mobile=mobile, otp=otp)
        # Fetch freshly recalculated prediction data
        fresh_data = get_opd_prediction_data()
        return JsonResponse({
            "status": "success",
            "sync": sync_result,
            "data": fresh_data
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

def anc_analytics_api(request):
    json_path = os.path.join(os.path.dirname(__file__), "..", "data", "anc_journey_analytics.json")
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
        return JsonResponse({"status": "success", "data": data})
    return JsonResponse({"status": "error", "message": "Analytics file not found"}, status=404)

def anc_patients_filter_api(request):
    """
    Live API to filter patients who conceived from IUI/IVF and converted to ANC,
    including their date of ANC entry, baby birth/delivery status, baby details, or loss reason.
    """
    from django.db import connection
    start_date = request.GET.get("start_date", "2026-01-01").strip()
    end_date = request.GET.get("end_date", "2026-01-31").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    treatment_type = request.GET.get("treatment_type", "all").strip()  # all, ivf, iui

    cursor = connection.cursor()

    treatment_clause = ""
    if treatment_type == "ivf":
        treatment_clause = """
            AND (
                EXISTS (SELECT 1 FROM ivf v WHERE v.patients_id = a.patients_id AND v.created_at <= a.created_at AND v.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
                OR EXISTS (SELECT 1 FROM fet_procedures f WHERE f.patients_id = a.patients_id AND f.created_at <= a.created_at AND f.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
            )
        """
    elif treatment_type == "iui":
        treatment_clause = """
            AND EXISTS (SELECT 1 FROM iui u WHERE u.patients_id = a.patients_id AND u.created_at <= a.created_at AND u.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
        """
    else:
        treatment_clause = """
            AND (
                EXISTS (SELECT 1 FROM ivf v WHERE v.patients_id = a.patients_id AND v.created_at <= a.created_at AND v.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
                OR EXISTS (SELECT 1 FROM iui u WHERE u.patients_id = a.patients_id AND u.created_at <= a.created_at AND u.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
                OR EXISTS (SELECT 1 FROM fet_procedures f WHERE f.patients_id = a.patients_id AND f.created_at <= a.created_at AND f.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY))
            )
        """

    query = f"""
        SELECT 
            a.patients_id,
            p.code,
            p.name,
            p.surname,
            p.mobile_number,
            a.branch_id,
            IFNULL(b.name, CONCAT('Branch ', a.branch_id)) as branch_name,
            MIN(a.created_at) as anc_date,
            CASE 
                WHEN EXISTS (SELECT 1 FROM ivf v WHERE v.patients_id = a.patients_id AND v.created_at <= a.created_at AND v.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY)) 
                     AND EXISTS (SELECT 1 FROM iui u WHERE u.patients_id = a.patients_id AND u.created_at <= a.created_at AND u.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY)) THEN 'Both IVF & IUI'
                WHEN EXISTS (SELECT 1 FROM ivf v WHERE v.patients_id = a.patients_id AND v.created_at <= a.created_at AND v.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY)) 
                     OR EXISTS (SELECT 1 FROM fet_procedures f WHERE f.patients_id = a.patients_id AND f.created_at <= a.created_at AND f.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY)) THEN 'IVF / FET'
                WHEN EXISTS (SELECT 1 FROM iui u WHERE u.patients_id = a.patients_id AND u.created_at <= a.created_at AND u.created_at >= DATE_SUB(a.created_at, INTERVAL 300 DAY)) THEN 'IUI'
                ELSE 'Fertility'
            END as conceived_from,
            CASE 
                WHEN term.delivery_type IS NOT NULL THEN CONCAT('Delivered (', term.delivery_type, ')')
                WHEN idc.delivery_type IS NOT NULL THEN CONCAT('Delivered (', idc.delivery_type, ')')
                WHEN idc.surgical_note LIKE '%%DELIVER%%' AND idc.surgical_note NOT LIKE '%%ABORTION%%' AND idc.surgical_note NOT LIKE '%%D&E%%' THEN 'Delivered (LSCS / Normal)'
                WHEN term.is_miss_abortion = 1 OR term.termination_type IS NOT NULL THEN 'No (Loss / Abortion)'
                WHEN idc.surgical_note LIKE '%%D&E%%' OR idc.surgical_note LIKE '%%CURETTAGE%%' OR idc.surgical_note LIKE '%%ABORTION%%' THEN 'No (Loss / Surgical Abortion)'
                WHEN a.is_anc_completed = 1 AND a.edd IS NOT NULL AND a.edd <= CURDATE() THEN 'ANC Completed / Delivered'
                WHEN a.edd IS NOT NULL AND a.edd < CURDATE() THEN 'Due Date Passed / Awaiting Delivery Card'
                ELSE 'Ongoing Pregnancy'
            END as baby_status,
            CASE 
                WHEN ch.gender IS NOT NULL OR ch.baby_weight IS NOT NULL THEN 
                    CONCAT(IFNULL(ch.gender, ''), IF(ch.baby_weight, CONCAT(', Wt: ', ch.baby_weight, 'kg'), ''), IF(ch.date_of_birth, CONCAT(' on ', ch.date_of_birth), ''))
                WHEN idc.surgical_note LIKE '%%DELIVER%%' AND idc.surgical_note NOT LIKE '%%ABORTION%%' AND idc.surgical_note NOT LIKE '%%D&E%%' THEN 
                    SUBSTRING(idc.surgical_note, 1, 100)
                ELSE '-'
            END as baby_details,
            CASE 
                WHEN term.miss_abortion IS NOT NULL THEN term.miss_abortion
                WHEN term.termination_type IS NOT NULL THEN term.termination_type
                WHEN idc.surgical_note LIKE '%%D&E%%' OR idc.surgical_note LIKE '%%CURETTAGE%%' OR idc.surgical_note LIKE '%%ABORTION%%' THEN SUBSTRING(idc.surgical_note, 1, 100)
                ELSE '-'
            END as loss_reason,
            a.edd
        FROM anc a
        JOIN patients p ON a.patients_id = p.id
        LEFT JOIN branch b ON a.branch_id = b.id
        LEFT JOIN anc_terminations term ON term.patients_id = a.patients_id AND term.created_at >= a.created_at
        LEFT JOIN anc_termination_children ch ON term.id = ch.anc_termination_id
        LEFT JOIN indoor_books ib ON ib.patient_id = a.patients_id AND ib.created_at >= a.created_at
        LEFT JOIN indoor_discharge_cards idc ON idc.booking_id = ib.id
        WHERE a.created_at BETWEEN %s AND %s
          AND (%s = '' OR a.branch_id = %s)
          {treatment_clause}
        GROUP BY a.patients_id, a.created_at, p.code, p.name, p.surname, p.mobile_number, a.branch_id, b.name,
                 term.delivery_type, idc.delivery_type, idc.surgical_note, a.is_anc_completed,
                 term.is_miss_abortion, term.termination_type, term.miss_abortion, a.edd,
                 ch.gender, ch.baby_weight, ch.date_of_birth
        ORDER BY anc_date ASC
    """

    cursor.execute(query, [start_date + " 00:00:00", end_date + " 23:59:59", branch_id, branch_id])
    rows = cursor.fetchall()

    patients_list = []
    delivered_count = 0
    loss_count = 0
    ongoing_count = 0

    seen_pids = set()
    for r in rows:
        pid = r[0]
        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        fname = r[2].strip() if r[2] else ""
        sname = r[3].strip() if r[3] else ""
        if sname and sname.lower() in fname.lower():
            full_name = fname
        else:
            full_name = f"{fname} {sname}".strip()

        status_text = r[9]
        if "Delivered" in status_text or "Completed" in status_text:
            delivered_count += 1
            status_badge = "delivered"
        elif "Loss" in status_text or "Abortion" in status_text:
            loss_count += 1
            status_badge = "loss"
        else:
            ongoing_count += 1
            status_badge = "ongoing"

        edd_val = r[12]
        edd_str = edd_val.strftime("%Y-%m-%d") if edd_val else "-"

        patients_list.append({
            "patient_id": r[0],
            "code": r[1],
            "name": full_name,
            "mobile": r[4] or "-",
            "branch_id": r[5],
            "branch_name": r[6],
            "anc_date": r[7].strftime("%Y-%m-%d %H:%M") if r[7] else "-",
            "conceived_from": r[8],
            "baby_status": status_text,
            "status_badge": status_badge,
            "baby_details": r[10] or "-",
            "loss_reason": r[11] or "-",
            "edd": edd_str,
        })

    return JsonResponse({
        "status": "success",
        "total_patients": len(patients_list),
        "delivered_count": delivered_count,
        "loss_count": loss_count,
        "ongoing_count": ongoing_count,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "treatment_type": treatment_type,
        },
        "patients": patients_list
    })

def extract_request_payload(request):
    if request.body:
        try:
            return json.loads(request.body.decode("utf-8"))
        except Exception:
            pass
    if request.method == "POST":
        return request.POST.dict()
    return request.GET.dict()

@csrf_exempt
def predict_iui_api(request):
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Only POST or GET methods allowed"}, status=405)
    try:
        data = extract_request_payload(request)
        predictor = get_iui_predictor()
        result = predictor.predict(data)
        
        try:
            PredictionLog.objects.create(
                table_source="iui_history",
                cycle_day=float(data.get("lmp_diff", data.get("cycle_day", 2)) or 2),
                endometrial_thickness=float(data.get("endo_size", data.get("endometrial_thickness", 1.0)) or 1.0),
                endometrial_pattern=data.get("husband_factor", "Normal"),
                left_max_follicle=float(data.get("left_afc", 0.0) or 0.0),
                right_max_follicle=float(data.get("right_afc", 0.0) or 0.0),
                dominant_follicle=float(data.get("left_afc", 0) or 0) + float(data.get("right_afc", 0) or 0),
                hcg_trigger=bool(data.get("vascularity_of_endo", 0)),
                medication=data.get("pcos_pattern", "0"),
                predicted_description=result["suggested_plan"],
                confidence=result["confidence"],
                recommended_plan=result["suggested_plan"]
            )
        except Exception:
            pass

        return JsonResponse(sanitize_for_json({
            "status": "success",
            "treatment_type": "IUI",
            "suggested_plan": result["suggested_plan"],
            "confidence": result["confidence"],
            "confidence_percentage": result["confidence_percentage"],
            "success_rate": result["success_rate"],
            "success_rate_percentage": result["success_rate_percentage"],
            "success_rate_numeric": result["success_rate_numeric"],
            "positive_outcome_forecast": result.get("positive_outcome_forecast"),
            "conception_probability": result.get("conception_probability"),
            "conception_probability_formatted": result.get("conception_probability_formatted"),
            "recommended_protocol": result["recommended_protocol"],
            "clinical_rationale": result["clinical_rationale"],
            "shared_biomarkers": result["shared_biomarkers"],
            "historical_conception_rate": result["historical_conception_rate"],
            "typical_afc_range": result["typical_afc_range"],
            "detected_criteria": result["detected_criteria"],
            "predicted_treatment": result.get("predicted_treatment"),
            "treatment_medicines": result.get("treatment_medicines", []),
            "predicted_investigation": result.get("predicted_investigation"),
            "investigation_tests": result.get("investigation_tests", []),
            "investigation_json": result.get("investigation_json", {}),
            "predicted_protocol": result.get("predicted_protocol"),
            "daily_injections": result.get("daily_injections", []),
            "description_json": result.get("description_json", {}),
            "predicted_package": result.get("predicted_package"),
            "package_name": result.get("package_name"),
            "package_estimated_cost": result.get("package_estimated_cost"),
            "package_cost_formatted": result.get("package_cost_formatted"),
            "package_cost_range": result.get("package_cost_range"),
            "alternative_plans": result["alternative_plans"],
            "failure_recovery_analysis": result.get("failure_recovery_analysis"),
            "similar_cases": result["similar_cases"],
            "inputs_received": result["inputs_received"],
            "data": result
        }))
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def predict_ivf_api(request):
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Only POST or GET methods allowed"}, status=405)
    try:
        data = extract_request_payload(request)
        predictor = get_ivf_predictor()
        result = predictor.predict(data)
        
        try:
            PredictionLog.objects.create(
                table_source="ivf_history",
                cycle_day=float(data.get("lmp_diff", data.get("cycle_day", 2)) or 2),
                endometrial_thickness=8.0,
                endometrial_pattern=data.get("endo_status", "Normal"),
                left_max_follicle=float(data.get("left_afc", 0.0) or 0.0),
                right_max_follicle=float(data.get("right_afc", 0.0) or 0.0),
                dominant_follicle=float(data.get("left_afc", 0) or 0) + float(data.get("right_afc", 0) or 0),
                hcg_trigger=bool(data.get("era_test_cycle", 0)),
                medication=result.get("recommended_protocol", "Standard"),
                predicted_description=result["suggested_plan"],
                confidence=result["confidence"],
                recommended_plan=result["suggested_plan"]
            )
        except Exception:
            pass

        return JsonResponse(sanitize_for_json({
            "status": "success",
            "treatment_type": "IVF",
            "suggested_plan": result["suggested_plan"],
            "confidence": result["confidence"],
            "confidence_percentage": result["confidence_percentage"],
            "success_rate": result["success_rate"],
            "success_rate_percentage": result["success_rate_percentage"],
            "success_rate_numeric": result["success_rate_numeric"],
            "positive_outcome_forecast": result.get("positive_outcome_forecast"),
            "conception_probability": result.get("conception_probability"),
            "conception_probability_formatted": result.get("conception_probability_formatted"),
            "recommended_protocol": result["recommended_protocol"],
            "clinical_rationale": result["clinical_rationale"],
            "shared_biomarkers": result["shared_biomarkers"],
            "historical_conception_rate": result["historical_conception_rate"],
            "typical_afc_range": result["typical_afc_range"],
            "detected_criteria": result["detected_criteria"],
            "predicted_treatment": result.get("predicted_treatment"),
            "treatment_medicines": result.get("treatment_medicines", []),
            "predicted_investigation": result.get("predicted_investigation"),
            "investigation_tests": result.get("investigation_tests", []),
            "investigation_json": result.get("investigation_json", {}),
            "predicted_protocol": result.get("predicted_protocol"),
            "daily_injections": result.get("daily_injections", []),
            "description_json": result.get("description_json", {}),
            "predicted_package": result.get("predicted_package"),
            "package_name": result.get("package_name"),
            "package_estimated_cost": result.get("package_estimated_cost"),
            "package_cost_formatted": result.get("package_cost_formatted"),
            "package_cost_range": result.get("package_cost_range"),
            "alternative_plans": result["alternative_plans"],
            "failure_recovery_analysis": result.get("failure_recovery_analysis"),
            "similar_cases": result["similar_cases"],
            "inputs_received": result["inputs_received"],
            "data": result
        }))
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def predict_plan_api(request):
    """
    Unified JSON API endpoint for both IUI and IVF.
    Accepts JSON body with optional "treatment_type": "iui" | "ivf"
    """
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Only POST or GET methods allowed"}, status=405)
    try:
        data = extract_request_payload(request)
        t_type = str(data.get("treatment_type", data.get("type", ""))).strip().lower()
        if "ivf" in t_type:
            return predict_ivf_api(request)
        elif "iui" in t_type:
            return predict_iui_api(request)
        else:
            if "era_test_cycle" in data or "endo_status" in data:
                return predict_ivf_api(request)
            return predict_iui_api(request)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def compare_protocols_api(request):
    """
    Side-by-side What-If Scenarios Comparison API.
    Computes and compares Scenario A (e.g., IUI Cycle with HMG 150) and Scenario B (e.g., IVF / FET Escalation)
    for clinical success rate, estimated total costs, pharmacy expenses, procedure timelines, and risk assessments.
    """
    if request.method not in ["POST", "GET"]:
        return JsonResponse({"error": "Only POST or GET methods allowed"}, status=405)
    try:
        data = extract_request_payload(request)
        patient_inputs = data.get("patient_inputs", data)
        
        scenario_a_type = str(data.get("scenario_a_type", "iui")).lower()
        scenario_b_type = str(data.get("scenario_b_type", "ivf")).lower()
        
        # Scenario A Evaluation
        if "ivf" in scenario_a_type:
            predictor_a = get_ivf_predictor()
            res_a = predictor_a.predict(patient_inputs)
            label_a = res_a.get("suggested_plan", "IVF Treatment")
            type_a = "IVF / ICSI"
        else:
            predictor_a = get_iui_predictor()
            res_a = predictor_a.predict(patient_inputs)
            label_a = res_a.get("suggested_plan", "IUI Treatment")
            type_a = "IUI"
            
        # Scenario B Evaluation (with escalation/IVF settings if evaluating IVF)
        b_inputs = dict(patient_inputs)
        if "ivf" in scenario_b_type:
            predictor_b = get_ivf_predictor()
            # If comparing to IVF escalation, ensure suitable IVF parameters
            if "cycle_no" in b_inputs and int(b_inputs.get("cycle_no", 1)) < 2:
                b_inputs["cycle_no"] = 2
            res_b = predictor_b.predict(b_inputs)
            label_b = res_b.get("suggested_plan", "IVF / FET Protocol")
            type_b = "IVF / ICSI"
        else:
            predictor_b = get_iui_predictor()
            res_b = predictor_b.predict(b_inputs)
            label_b = res_b.get("suggested_plan", "IUI Protocol")
            type_b = "IUI"

        pkg_a = res_a.get("predicted_package", {})
        pkg_b = res_b.get("predicted_package", {})

        cost_a = pkg_a.get("estimated_total_cost", 18500.0)
        cost_b = pkg_b.get("estimated_total_cost", 165000.0)

        rate_a = res_a.get("positive_outcome_forecast", {}).get("conception_probability") or res_a.get("success_rate_numeric", 18.8)
        rate_b = res_b.get("positive_outcome_forecast", {}).get("conception_probability") or res_b.get("success_rate_numeric", 48.7)

        # Build comparison delta insights
        rate_diff = round(float(rate_b) - float(rate_a), 1)
        cost_diff = round(float(cost_b) - float(cost_a), 2)

        comparison = {
            "scenario_a": {
                "type": type_a,
                "plan_name": label_a,
                "protocol": res_a.get("recommended_protocol", ""),
                "conception_rate": rate_a,
                "conception_rate_formatted": f"{rate_a}%",
                "estimated_cost": cost_a,
                "formatted_cost": pkg_a.get("formatted_cost", f"₹{int(cost_a):,}"),
                "cost_range": pkg_a.get("cost_range", "Standard Clinic Pricing"),
                "pharmacy_total": pkg_a.get("pharmacy_grand_total_formatted", "₹4,200"),
                "procedure_invasiveness": "Low Invasiveness (Outpatient, No Anaesthesia, Natural/Mild Stimulation)",
                "cycles_to_pregnancy": "Requires 2 - 4 Cumulative Cycles (Typical)",
                "cumulative_success": "38% - 48% over 3 Cycles",
                "clinical_timeline": "14 - 18 Days Per Cycle",
                "advantages": [
                    "Non-invasive outpatient procedure without anaesthesia",
                    "Significantly lower financial commitment per cycle",
                    "Natural physiological conception with washed motile sperm selection"
                ],
                "considerations": [
                    "Requires patent fallopian tubes (bilateral blockage gives 0% chance)",
                    "Diminished returns after 3 unsuccessful attempts",
                    "Relies on natural sperm-egg interaction in vivo"
                ]
            },
            "scenario_b": {
                "type": type_b,
                "plan_name": label_b,
                "protocol": res_b.get("recommended_protocol", ""),
                "conception_rate": rate_b,
                "conception_rate_formatted": f"{rate_b}%",
                "estimated_cost": cost_b,
                "formatted_cost": pkg_b.get("formatted_cost", f"₹{int(cost_b):,}"),
                "cost_range": pkg_b.get("cost_range", "Standard Clinic Package"),
                "pharmacy_total": pkg_b.get("pharmacy_grand_total_formatted", "₹38,000"),
                "procedure_invasiveness": "Comprehensive ART (Ultrasound-Guided Oocyte Pick-Up Under Sedation + ICSI Lab)",
                "cycles_to_pregnancy": "1 - 2 Transfers (Highest Per-Cycle Success)",
                "cumulative_success": "72% - 84% over 1 Pick Up + 2 Frozen Embryo Transfers",
                "clinical_timeline": "4 - 6 Weeks (Stimulation, Retrieval & Blastocyst Cryopreservation)",
                "advantages": [
                    "Bypasses fallopian tube blockage completely",
                    "Overcomes severe male factor via ICSI / IMSI micromanipulation",
                    "Allows surplus blastocyst vitrification for future sibling cycles",
                    "Highest per-transfer conception probability (48% - 55%)"
                ],
                "considerations": [
                    "Higher upfront investment and pharmacy injection requirement",
                    "Requires minor surgical day-care procedure (sedation for ovum pick up)",
                    "Requires close serial ultrasound and estradiol blood monitoring"
                ]
            },
            "analytics_summary": {
                "success_rate_boost": f"+{rate_diff}% higher positive outcome with Scenario B",
                "cost_differential": f"₹{int(abs(cost_diff)):,} difference",
                "cost_per_success_percentage_a": f"₹{int(cost_a / max(rate_a, 1)):,} per 1% conception chance",
                "cost_per_success_percentage_b": f"₹{int(cost_b / max(rate_b, 1)):,} per 1% conception chance",
                "clinical_counseling_verdict": (
                    f"If the patient has patent fallopian tubes and under 3 prior IUI attempts, {label_a} is financially efficient. "
                    f"However, if tubal blockage, severe male factor, or advanced maternal age (>35) is present, escalating to {label_b} yields a +{rate_diff}% higher immediate pregnancy rate and saves cumulative months of delay."
                )
            }
        }

        return JsonResponse(sanitize_for_json({
            "status": "success",
            "comparison": comparison
        }))
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

def history_api(request):
    logs = list(PredictionLog.objects.all().order_by("-created_at")[:50].values())
    return JsonResponse({"status": "success", "history": logs})

