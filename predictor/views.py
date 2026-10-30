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

# Feature Flags for modules (set ENABLE_PREDICTIVE_ENGINES = True in future to re-enable)
ENABLE_PREDICTIVE_ENGINES = False

def root_redirect(request):
    return redirect("opd_report_page")

def iui_page(request):
    if not ENABLE_PREDICTIVE_ENGINES:
        return redirect("opd_report_page")
    return render(request, "predictor/iui.html")

def ivf_page(request):
    if not ENABLE_PREDICTIVE_ENGINES:
        return redirect("opd_report_page")
    return render(request, "predictor/ivf.html")

def anc_journey_page(request):
    if not ENABLE_PREDICTIVE_ENGINES:
        return redirect("opd_report_page")
    return render(request, "predictor/anc_journey.html")

def opd_prediction_page(request):
    if not ENABLE_PREDICTIVE_ENGINES:
        return redirect("opd_report_page")
    return render(request, "predictor/opd_prediction.html")

def opd_report_page(request):
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('SELECT id, name FROM branch WHERE status = 1 ORDER BY name')
    branches = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]
    cursor.execute('SELECT id, name FROM category WHERE status = 1 ORDER BY name')
    categories = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]
    return render(request, "predictor/opd_report.html", {
        'initial_branches': branches,
        'initial_categories': categories
    })

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
    view_mode = request.GET.get("view_mode", "").strip().lower()
    legacy_profit = request.GET.get("only_profit", "0").lower() in ("1", "true", "yes")
    if not view_mode:
        if legacy_profit:
            view_mode = "net_profit"
        else:
            view_mode = "none"
    elif view_mode in ("0", "false", "-", "standard"):
        view_mode = "none"
    elif view_mode in ("1", "true"):
        view_mode = "net_profit"

    is_gross_profit = (view_mode == "gross_profit")
    is_net_profit = (view_mode == "net_profit")
    is_profit_view = is_gross_profit or is_net_profit
    only_profit = is_profit_view

    where_clauses = ["mpi.is_deleted = 0", "mpi.department_id = 1"]
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
    # As requested: Pharmacy collection is computed from Sales Register (mpi) minus Sales Return Register (msc).
    # Without GST uses Taxable amounts (mpi.sell_price_without_gst - msc.price_without_gst).
    # With GST uses Gross amounts (mpi.sell_price - msc.payable_amount).
    if exclude_gst:
        s_price_col = "mpi.sell_price_without_gst"
        r_price_col = "msc.price_without_gst"
        s_cash_col = "mpi.payment_cash * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        s_upi_col = "mpi.payment_upi * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        s_cheque_col = "mpi.payment_cheque * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        s_neft_col = "mpi.payment_neft * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        r_cash_col = "msc.payment_cash * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        r_upi_col = "msc.payment_upi * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        r_cheque_col = "msc.payment_cheque * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        r_neft_col = "msc.payment_neft * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
    else:
        s_price_col = "mpi.sell_price"
        r_price_col = "msc.payable_amount"
        s_cash_col = "mpi.payment_cash"
        s_upi_col = "mpi.payment_upi"
        s_cheque_col = "mpi.payment_cheque"
        s_neft_col = "mpi.payment_neft"
        r_cash_col = "msc.payment_cash"
        r_upi_col = "msc.payment_upi"
        r_cheque_col = "msc.payment_cheque"
        r_neft_col = "msc.payment_neft"

    # Filters for Returns (msc) - Medical Store only (department_id = 1)
    pr_where = ["msc.department_id = 1"]
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

    # 1A. Sales Register Aggregate
    kpi_sales_query = f"""
        SELECT 
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({price_col}), 0) as total_bill_amount,
            COALESCE(SUM({s_price_col}), 0) as sales_collection,
            COALESCE(SUM({s_cash_col}), 0) as sales_cash,
            COALESCE(SUM({s_upi_col}), 0) as sales_upi,
            COALESCE(SUM({s_cheque_col}), 0) as sales_cheque,
            COALESCE(SUM({s_neft_col}), 0) as sales_neft,
            
            -- IVF
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {s_price_col} ELSE 0 END), 0) as ivf_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {price_col} ELSE 0 END), 0) as ivf_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN mpi.id ELSE NULL END) as ivf_invoices,

            -- INF
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {s_price_col} ELSE 0 END), 0) as inf_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {price_col} ELSE 0 END), 0) as inf_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN mpi.id ELSE NULL END) as inf_invoices,

            -- IUI
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {s_price_col} ELSE 0 END), 0) as iui_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {price_col} ELSE 0 END), 0) as iui_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN mpi.id ELSE NULL END) as iui_invoices,

            -- ANC
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {s_price_col} ELSE 0 END), 0) as anc_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {price_col} ELSE 0 END), 0) as anc_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN mpi.id ELSE NULL END) as anc_invoices,

            -- GYNEC
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {s_price_col} ELSE 0 END), 0) as gynec_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {price_col} ELSE 0 END), 0) as gynec_bill,
            COUNT(DISTINCT CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN mpi.id ELSE NULL END) as gynec_invoices,

            -- Other / General
            COALESCE(SUM(CASE WHEN c.name IS NULL 
                                   OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                       AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                       AND LOWER(c.name) NOT LIKE '%%gynec%%')
                              THEN {s_price_col} ELSE 0 END), 0) as other_sales,
            COALESCE(SUM(CASE WHEN c.name IS NULL 
                                   OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                       AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                       AND LOWER(c.name) NOT LIKE '%%gynec%%')
                              THEN {price_col} ELSE 0 END), 0) as other_bill,
            COUNT(DISTINCT CASE WHEN c.name IS NULL 
                                     OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                         AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                         AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                         AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                         AND LOWER(c.name) NOT LIKE '%%gynec%%')
                                THEN mpi.id ELSE NULL END) as other_invoices,
            
            -- Auxiliary Profit Reference
            COALESCE(SUM({profit_col}), 0) as raw_profit_billed
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        WHERE {where_sql}
    """
    cursor.execute(kpi_sales_query, params)
    s_row = cursor.fetchone()

    # 1B. Sales Return Register Aggregate
    kpi_return_query = f"""
        SELECT 
            COUNT(DISTINCT msc.id) as return_notes,
            COALESCE(SUM({r_price_col}), 0) as ret_collection,
            COALESCE(SUM({r_cash_col}), 0) as ret_cash,
            COALESCE(SUM({r_upi_col}), 0) as ret_upi,
            COALESCE(SUM({r_cheque_col}), 0) as ret_cheque,
            COALESCE(SUM({r_neft_col}), 0) as ret_neft,
            
            -- IVF Returns
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {r_price_col} ELSE 0 END), 0) as ivf_ret,
            -- INF Returns
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {r_price_col} ELSE 0 END), 0) as inf_ret,
            -- IUI Returns
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {r_price_col} ELSE 0 END), 0) as iui_ret,
            -- ANC Returns
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {r_price_col} ELSE 0 END), 0) as anc_ret,
            -- GYNEC Returns
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {r_price_col} ELSE 0 END), 0) as gynec_ret,
            -- Other Returns
            COALESCE(SUM(CASE WHEN c.name IS NULL 
                                   OR (LOWER(c.name) NOT LIKE '%%ivf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%inf%%' 
                                       AND LOWER(c.name) NOT LIKE '%%iui%%' 
                                       AND LOWER(c.name) NOT LIKE '%%anc%%' 
                                       AND LOWER(c.name) NOT LIKE '%%gynec%%')
                              THEN {r_price_col} ELSE 0 END), 0) as other_ret
        FROM medication_sales_credit msc
        LEFT JOIN medication_patients_invoices mpi ON msc.medication_patients_invoice_id = mpi.id
        LEFT JOIN category c ON mpi.category_id = c.id
        WHERE {pr_where_sql}
    """
    cursor.execute(kpi_return_query, pr_params)
    r_row = cursor.fetchone()

    total_invoices = int(s_row[0] or 0)
    total_bill_amount = float(s_row[1] or 0.0)
    
    # Net Pharmacy Collection = Sales Register - Sales Return Register
    sales_coll = float(s_row[2] or 0.0)
    ret_coll = float(r_row[1] or 0.0)
    total_pharmacy_collection = round(sales_coll - ret_coll, 2)

    total_cash = max(0.0, round(float(s_row[3] or 0.0) - float(r_row[2] or 0.0), 2))
    total_upi = max(0.0, round(float(s_row[4] or 0.0) - float(r_row[3] or 0.0), 2))
    total_cheque = max(0.0, round(float(s_row[5] or 0.0) - float(r_row[4] or 0.0), 2))
    total_neft = max(0.0, round(float(s_row[6] or 0.0) - float(r_row[5] or 0.0), 2))

    ivf_income = round(float(s_row[7] or 0.0) - float(r_row[6] or 0.0), 2)
    ivf_bill = float(s_row[8] or 0.0)
    ivf_inv_cnt = int(s_row[9] or 0)

    inf_income = round(float(s_row[10] or 0.0) - float(r_row[7] or 0.0), 2)
    inf_bill = float(s_row[11] or 0.0)
    inf_inv_cnt = int(s_row[12] or 0)

    iui_income = round(float(s_row[13] or 0.0) - float(r_row[8] or 0.0), 2)
    iui_bill = float(s_row[14] or 0.0)
    iui_inv_cnt = int(s_row[15] or 0)

    anc_income = round(float(s_row[16] or 0.0) - float(r_row[9] or 0.0), 2)
    anc_bill = float(s_row[17] or 0.0)
    anc_inv_cnt = int(s_row[18] or 0)

    gynec_income = round(float(s_row[19] or 0.0) - float(r_row[10] or 0.0), 2)
    gynec_bill = float(s_row[20] or 0.0)
    gynec_inv_cnt = int(s_row[21] or 0)

    other_income = round(float(s_row[22] or 0.0) - float(r_row[11] or 0.0), 2)
    other_bill = float(s_row[23] or 0.0)
    other_inv_cnt = int(s_row[24] or 0)

    raw_total_collection = total_pharmacy_collection
    raw_total_bill = total_bill_amount
    raw_profit_billed = float(s_row[25] or 0.0)
    raw_profit_collected = raw_profit_billed

    # --- Node-Backend Trading Profit-Loss Calculation (Gross Profit & Net Profit = GP - MIX EXP) ---
    b_sql = " AND branch_id = %s" if branch_id else ""
    b_param = [branch_id] if branch_id else []

    # 1. Stock Opening: date_of_transaction < start_date
    if start_date:
        cursor.execute(f"""
            SELECT (SUM(in_qty * reference_unit_purchase_price_without_gst) - SUM(out_qty * reference_unit_purchase_price_without_gst))
            FROM medication_transaction
            WHERE department_id = 1 {b_sql} AND date_of_transaction < %s
        """, b_param + [start_date])
        stock_opening_amount = float(cursor.fetchone()[0] or 0.0)
    else:
        stock_opening_amount = 0.0

    # 2. Purchase & Purchase Return
    p_where = ["department_id = 1"]
    p_params = []
    if branch_id:
        p_where.append("branch_id = %s")
        p_params.append(branch_id)
    if start_date:
        p_where.append("date_of_transaction >= %s")
        p_params.append(start_date)
    if end_date:
        p_where.append("date_of_transaction <= %s")
        p_params.append(end_date)
    p_where_sql = " AND ".join(p_where)

    cursor.execute(f"SELECT COALESCE(SUM(taxable_amount), 0) FROM medication_purchase_invoices WHERE {p_where_sql}", p_params)
    purchase_amount = float(cursor.fetchone()[0] or 0.0)

    cursor.execute(f"SELECT COALESCE(SUM(price_without_gst), 0) FROM medication_purchase_debit WHERE {p_where_sql}", p_params)
    purchase_return_amount = float(cursor.fetchone()[0] or 0.0)

    # 3. Stock Closing: date_of_transaction <= end_date
    if end_date:
        cursor.execute(f"""
            SELECT (SUM(in_qty * reference_unit_purchase_price_without_gst) - SUM(out_qty * reference_unit_purchase_price_without_gst))
            FROM medication_transaction
            WHERE department_id = 1 {b_sql} AND date_of_transaction <= %s
        """, b_param + [end_date])
        stock_closing_amount = float(cursor.fetchone()[0] or 0.0)
    else:
        cursor.execute(f"""
            SELECT (SUM(in_qty * reference_unit_purchase_price_without_gst) - SUM(out_qty * reference_unit_purchase_price_without_gst))
            FROM medication_transaction
            WHERE department_id = 1 {b_sql}
        """, b_param)
        stock_closing_amount = float(cursor.fetchone()[0] or 0.0)

    # 4. MIX EXP: type = 0 cash expenses from medication_cash_expenses
    cursor.execute(f"""
        SELECT COALESCE(SUM(amount), 0)
        FROM medication_cash_expenses
        WHERE type = 0 AND {p_where_sql}
    """, p_params)
    mix_exp_amount = float(cursor.fetchone()[0] or 0.0)

    # 5. COGS & Gross Profit & Net Profit
    cogs_amount = round(stock_opening_amount + (purchase_amount - purchase_return_amount) - stock_closing_amount, 2)
    # Net sales is sales_coll - ret_coll (Taxable amount without GST)
    trading_net_sales = sales_coll - ret_coll
    gross_profit_amount = round(trading_net_sales - cogs_amount, 2)
    net_profit_amount = round(gross_profit_amount - mix_exp_amount, 2)

    # Apply Active View Mode to Main Display Metrics
    if is_gross_profit:
        display_collection = gross_profit_amount
        prefix = "Gross Profit"
    elif is_net_profit:
        display_collection = net_profit_amount
        prefix = "Net Profit"
    else:
        display_collection = total_pharmacy_collection
        prefix = "Medicine Income"

    # Distribute category profit proportionally if in profit mode
    if is_profit_view and total_pharmacy_collection > 0:
        cat_mult = (display_collection / total_pharmacy_collection)
        disp_ivf = round(ivf_income * cat_mult, 2)
        disp_anc = round(anc_income * cat_mult, 2)
        disp_inf = round(inf_income * cat_mult, 2)
        disp_gynec = round(gynec_income * cat_mult, 2)
        disp_iui = round(iui_income * cat_mult, 2)
        disp_other = round(other_income * cat_mult, 2)
    else:
        disp_ivf = ivf_income
        disp_anc = anc_income
        disp_inf = inf_income
        disp_gynec = gynec_income
        disp_iui = iui_income
        disp_other = other_income

    profit_margin_pct = round((gross_profit_amount / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0.0
    net_profit_margin_pct = round((net_profit_amount / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0.0

    # Categories list with percentage share
    categories_breakdown = [
        {
            "key": "IVF",
            "name": f"IVF {prefix}",
            "collection": disp_ivf,
            "bill_amount": ivf_bill,
            "invoices": ivf_inv_cnt,
            "pct": round((disp_ivf / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#0284C7",
            "bg_color": "rgba(2, 132, 199, 0.12)",
            "icon": "🧬"
        },
        {
            "key": "ANC",
            "name": f"ANC {prefix}",
            "collection": disp_anc,
            "bill_amount": anc_bill,
            "invoices": anc_inv_cnt,
            "pct": round((disp_anc / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#10B981",
            "bg_color": "rgba(16, 185, 129, 0.12)",
            "icon": "👶"
        },
        {
            "key": "INF",
            "name": f"INF {prefix}",
            "collection": disp_inf,
            "bill_amount": inf_bill,
            "invoices": inf_inv_cnt,
            "pct": round((disp_inf / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#8B5CF6",
            "bg_color": "rgba(139, 92, 246, 0.12)",
            "icon": "💊"
        },
        {
            "key": "GYNEC",
            "name": f"GYNEC {prefix}",
            "collection": disp_gynec,
            "bill_amount": gynec_bill,
            "invoices": gynec_inv_cnt,
            "pct": round((disp_gynec / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#EC4899",
            "bg_color": "rgba(236, 72, 153, 0.12)",
            "icon": "🌸"
        },
        {
            "key": "IUI",
            "name": f"IUI {prefix}",
            "collection": disp_iui,
            "bill_amount": iui_bill,
            "invoices": iui_inv_cnt,
            "pct": round((disp_iui / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#F59E0B",
            "bg_color": "rgba(245, 158, 11, 0.12)",
            "icon": "🔬"
        },
        {
            "key": "OTHER",
            "name": f"Other {prefix}",
            "collection": disp_other,
            "bill_amount": other_bill,
            "invoices": other_inv_cnt,
            "pct": round((disp_other / display_collection * 100), 1) if display_collection > 0 else 0,
            "color": "#64748B",
            "bg_color": "rgba(100, 116, 139, 0.12)",
            "icon": "🏥"
        }
    ]

    # Query 2: Monthly Timeline Trend (Net = Sales Register - Return Register)
    monthly_sales_query = f"""
        SELECT 
            DATE_FORMAT(mpi.date_of_transaction, '%%Y-%%m') as month_str,
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({s_price_col}), 0) as total_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {s_price_col} ELSE 0 END), 0) as ivf_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {s_price_col} ELSE 0 END), 0) as inf_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {s_price_col} ELSE 0 END), 0) as iui_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {s_price_col} ELSE 0 END), 0) as anc_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {s_price_col} ELSE 0 END), 0) as gynec_sales
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        WHERE {where_sql} AND mpi.date_of_transaction IS NOT NULL
        GROUP BY month_str
        ORDER BY month_str ASC
    """
    cursor.execute(monthly_sales_query, params)
    monthly_sales_map = {
        mr[0]: {
            "invoices": int(mr[1] or 0),
            "sales": float(mr[2] or 0.0),
            "ivf": float(mr[3] or 0.0),
            "inf": float(mr[4] or 0.0),
            "iui": float(mr[5] or 0.0),
            "anc": float(mr[6] or 0.0),
            "gynec": float(mr[7] or 0.0),
        }
        for mr in cursor.fetchall()
    }

    monthly_ret_query = f"""
        SELECT 
            DATE_FORMAT(msc.date_of_transaction, '%%Y-%%m') as month_str,
            COALESCE(SUM({r_price_col}), 0) as total_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {r_price_col} ELSE 0 END), 0) as ivf_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {r_price_col} ELSE 0 END), 0) as inf_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {r_price_col} ELSE 0 END), 0) as iui_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {r_price_col} ELSE 0 END), 0) as anc_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {r_price_col} ELSE 0 END), 0) as gynec_ret
        FROM medication_sales_credit msc
        LEFT JOIN medication_patients_invoices mpi ON msc.medication_patients_invoice_id = mpi.id
        LEFT JOIN category c ON mpi.category_id = c.id
        WHERE {pr_where_sql} AND msc.date_of_transaction IS NOT NULL
        GROUP BY month_str
        ORDER BY month_str ASC
    """
    cursor.execute(monthly_ret_query, pr_params)
    monthly_ret_map = {
        mr[0]: {
            "ret": float(mr[1] or 0.0),
            "ivf": float(mr[2] or 0.0),
            "inf": float(mr[3] or 0.0),
            "iui": float(mr[4] or 0.0),
            "anc": float(mr[5] or 0.0),
            "gynec": float(mr[6] or 0.0),
        }
        for mr in cursor.fetchall()
    }

    all_months = sorted(list(set(list(monthly_sales_map.keys()) + list(monthly_ret_map.keys()))))
    monthly_trend = []
    for ym in all_months:
        s_m = monthly_sales_map.get(ym, {"invoices": 0, "sales": 0, "ivf": 0, "inf": 0, "iui": 0, "anc": 0, "gynec": 0})
        r_m = monthly_ret_map.get(ym, {"ret": 0, "ivf": 0, "inf": 0, "iui": 0, "anc": 0, "gynec": 0})
        monthly_trend.append({
            "month": ym,
            "invoices": s_m["invoices"],
            "total_collection": round(s_m["sales"] - r_m["ret"], 2),
            "ivf_income": round(s_m["ivf"] - r_m["ivf"], 2),
            "inf_income": round(s_m["inf"] - r_m["inf"], 2),
            "iui_income": round(s_m["iui"] - r_m["iui"], 2),
            "anc_income": round(s_m["anc"] - r_m["anc"], 2),
            "gynec_income": round(s_m["gynec"] - r_m["gynec"], 2)
        })

    # Query 3: Branch Breakdown (Net = Sales Register - Return Register)
    branch_sales_query = f"""
        SELECT 
            mpi.branch_id,
            COALESCE(b.name, CONCAT('Branch ', mpi.branch_id)) as branch_name,
            COUNT(DISTINCT mpi.id) as total_invoices,
            COALESCE(SUM({s_price_col}), 0) as total_sales,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {s_price_col} ELSE 0 END), 0) as ivf_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {s_price_col} ELSE 0 END), 0) as inf_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {s_price_col} ELSE 0 END), 0) as iui_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {s_price_col} ELSE 0 END), 0) as anc_income,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {s_price_col} ELSE 0 END), 0) as gynec_income
        FROM medication_patients_invoices mpi
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN branch b ON mpi.branch_id = b.id
        WHERE {where_sql}
        GROUP BY mpi.branch_id, b.name
    """
    cursor.execute(branch_sales_query, params)
    branch_sales_map = {
        br[0]: {
            "name": br[1],
            "invoices": int(br[2] or 0),
            "sales": float(br[3] or 0.0),
            "ivf": float(br[4] or 0.0),
            "inf": float(br[5] or 0.0),
            "iui": float(br[6] or 0.0),
            "anc": float(br[7] or 0.0),
            "gynec": float(br[8] or 0.0),
        }
        for br in cursor.fetchall()
    }

    branch_ret_query = f"""
        SELECT 
            msc.branch_id,
            COALESCE(b.name, CONCAT('Branch ', msc.branch_id)) as branch_name,
            COALESCE(SUM({r_price_col}), 0) as total_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%ivf%%' THEN {r_price_col} ELSE 0 END), 0) as ivf_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%inf%%' THEN {r_price_col} ELSE 0 END), 0) as inf_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%iui%%' THEN {r_price_col} ELSE 0 END), 0) as iui_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%anc%%' THEN {r_price_col} ELSE 0 END), 0) as anc_ret,
            COALESCE(SUM(CASE WHEN LOWER(c.name) LIKE '%%gynec%%' THEN {r_price_col} ELSE 0 END), 0) as gynec_ret
        FROM medication_sales_credit msc
        LEFT JOIN medication_patients_invoices mpi ON msc.medication_patients_invoice_id = mpi.id
        LEFT JOIN category c ON mpi.category_id = c.id
        LEFT JOIN branch b ON msc.branch_id = b.id
        WHERE {pr_where_sql}
        GROUP BY msc.branch_id, b.name
    """
    cursor.execute(branch_ret_query, pr_params)
    branch_ret_map = {
        br[0]: {
            "name": br[1],
            "ret": float(br[2] or 0.0),
            "ivf": float(br[3] or 0.0),
            "inf": float(br[4] or 0.0),
            "iui": float(br[5] or 0.0),
            "anc": float(br[6] or 0.0),
            "gynec": float(br[7] or 0.0),
        }
        for br in cursor.fetchall()
    }

    all_branches_ids = sorted(list(set(list(branch_sales_map.keys()) + list(branch_ret_map.keys()))))
    branch_breakdown = []
    for bid in all_branches_ids:
        bs = branch_sales_map.get(bid, {"name": f"Branch {bid}", "invoices": 0, "sales": 0, "ivf": 0, "inf": 0, "iui": 0, "anc": 0, "gynec": 0})
        br = branch_ret_map.get(bid, {"name": bs["name"], "ret": 0, "ivf": 0, "inf": 0, "iui": 0, "anc": 0, "gynec": 0})
        b_name = bs["name"] or br["name"] or f"Branch {bid}"
        b_coll = round(bs["sales"] - br["ret"], 2)
        branch_breakdown.append({
            "branch_id": bid,
            "branch_name": b_name,
            "invoices": bs["invoices"],
            "total_collection": b_coll,
            "ivf_income": round(bs["ivf"] - br["ivf"], 2),
            "inf_income": round(bs["inf"] - br["inf"], 2),
            "iui_income": round(bs["iui"] - br["iui"], 2),
            "anc_income": round(bs["anc"] - br["anc"], 2),
            "gynec_income": round(bs["gynec"] - br["gynec"], 2),
            "share_pct": round((b_coll / total_pharmacy_collection * 100), 1) if total_pharmacy_collection > 0 else 0
        })
    branch_breakdown.sort(key=lambda x: x["total_collection"], reverse=True)

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
        "view_mode": view_mode,
        "only_profit": only_profit,
        "is_gross_profit": is_gross_profit,
        "is_net_profit": is_net_profit,
        "summary": {
            "total_invoices": total_invoices,
            "total_bill_amount": total_bill_amount,
            "total_pharmacy_collection": display_collection,
            "standard_collection": total_pharmacy_collection,
            "gross_profit": gross_profit_amount,
            "mix_exp": mix_exp_amount,
            "net_profit": net_profit_amount,
            "stock_opening": stock_opening_amount,
            "purchase_amount": purchase_amount,
            "purchase_return_amount": purchase_return_amount,
            "stock_closing": stock_closing_amount,
            "cogs": cogs_amount,
            "ivf_medicine_income": disp_ivf,
            "inf_medicine_income": disp_inf,
            "iui_medicine_income": disp_iui,
            "anc_medicine_income": disp_anc,
            "gynec_medicine_income": disp_gynec,
            "other_medicine_income": disp_other,
            "raw_total_collection": raw_total_collection,
            "raw_total_bill": raw_total_bill,
            "raw_profit_collected": raw_profit_collected,
            "raw_profit_billed": raw_profit_billed,
            "profit_margin_pct": profit_margin_pct,
            "net_profit_margin_pct": net_profit_margin_pct,
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
            "view_mode": view_mode,
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
    exclude_gst = request.GET.get("exclude_gst", "1").strip() == "1"
    exclude_cash = request.GET.get("exclude_cash", "0").strip() in ("1", "true", "yes")
    payment_type = request.GET.get("payment_type", "").strip()  # 1=Card, 2=Cash, 3=Cheque, 4=UPI, 5=NEFT

    cursor = connection.cursor()

    # --- 1. HEALTHCARE FILTERS (Strict parity with node-backend getNewCollectionReport) ---
    # Component A: indoor_deposits (is_deleted = 0)
    hc_where = ["d.case_type = 'Credit'"]
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
    if payment_type:
        hc_where.append("d.payment_type = %s")
        hc_params.append(payment_type)
    elif exclude_cash:
        hc_where.append("d.payment_type != 2")
    hc_where_sql = " AND ".join(hc_where)

    # Component B: appointment_charges
    ac_where = ["a.category_id != 7", "ac.total > 0"]
    ac_params = []
    if start_date:
        ac_where.append("a.date >= %s")
        ac_params.append(start_date)
    if end_date:
        ac_where.append("a.date <= %s")
        ac_params.append(end_date)
    if branch_id:
        ac_where.append("a.branch_id = %s")
        ac_params.append(branch_id)
    if payment_type:
        ac_where.append("ac.payment_mode = %s")
        ac_params.append(payment_type)
    elif exclude_cash:
        ac_where.append("ac.payment_mode != 2")
    ac_where_sql = " AND ".join(ac_where)

    # Component C: embryology_invoice (collection-day parity with invoice_vouchers date if available)
    ei_date_col = "COALESCE((SELECT iv.date FROM invoice_vouchers iv WHERE iv.finance_procedure = 'embryology_invoice' AND iv.entry_id = ei.id AND iv.branch_id = ei.branch_id AND iv.ivf_status = 0 ORDER BY iv.id DESC LIMIT 1), DATE(ei.created_at))"
    ei_where = ["(ei.payment_cash + ei.payment_upi + ei.payment_cheque + ei.payment_neft + ei.payment_card_swipe) > 0"]
    ei_params = []
    if start_date:
        ei_where.append(f"{ei_date_col} >= %s")
        ei_params.append(start_date)
    if end_date:
        ei_where.append(f"{ei_date_col} <= %s")
        ei_params.append(end_date)
    if branch_id:
        ei_where.append("ei.branch_id = %s")
        ei_params.append(branch_id)
    if exclude_cash:
        ei_where.append("(ei.payment_upi + ei.payment_cheque + ei.payment_neft + ei.payment_card_swipe) > 0")
    ei_where_sql = " AND ".join(ei_where)

    # Component D: income_manager (type = 1 and status = 1 expense categories)
    im_where = [
        "im.amount > 0",
        "im.income_category IN (SELECT ec.id FROM expance_category ec WHERE ec.type = 1 AND ec.status = 1)"
    ]
    im_params = []
    if start_date:
        im_where.append("DATE(im.date) >= %s")
        im_params.append(start_date)
    if end_date:
        im_where.append("DATE(im.date) <= %s")
        im_params.append(end_date)
    if branch_id:
        im_where.append("im.branch_id = %s")
        im_params.append(branch_id)
    if exclude_cash:
        im_where.append("im.payment_method NOT IN (1, 2)")
    im_where_sql = " AND ".join(im_where)

    # --- 2. PHARMACY COLLECTION FILTERS (Medical Store only: department_id = 1) ---
    ph_where = ["mpi.is_deleted = 0", "mpi.department_id = 1"]
    ph_params = []
    if start_date:
        ph_where.append("mpi.date_of_transaction >= %s")
        ph_params.append(start_date)
    if end_date:
        ph_where.append("mpi.date_of_transaction <= %s")
        ph_params.append(end_date)
    if branch_id:
        ph_where.append("mpi.branch_id = %s")
        ph_params.append(branch_id)
    ph_where_sql = " AND ".join(ph_where)

    # --- 3. PHARMACY RETURN FILTERS (Medical Store only: department_id = 1) ---
    pr_where = ["msc.department_id = 1"]
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

    # Cash expression switchers for pharmacy
    if exclude_cash:
        ph_modes_expr = "(COALESCE(mph.payment_upi, 0) + COALESCE(mph.payment_cheque, 0) + COALESCE(mph.payment_neft, 0))"
        pr_modes_expr = "(msc.payment_upi + msc.payment_cheque + msc.payment_neft)"
        pr_non_cash_ratio = "( (msc.payment_upi + msc.payment_cheque + msc.payment_neft) / NULLIF(msc.payable_amount, 0) )"
    else:
        ph_modes_expr = "(COALESCE(mph.payment_cash, 0) + COALESCE(mph.payment_upi, 0) + COALESCE(mph.payment_cheque, 0) + COALESCE(mph.payment_neft, 0))"
        pr_modes_expr = "(msc.payment_cash + msc.payment_upi + msc.payment_cheque + msc.payment_neft)"
        pr_non_cash_ratio = "1.0"

    # --- EXECUTE HEALTHCARE AGGREGATE ACROSS ALL 4 CLINICAL TABLES ---
    # 1. indoor_deposits
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

    # 2. appointment_charges
    ac_sql = f"""
        SELECT 
            COALESCE(SUM(ac.total), 0) as gross_ac,
            COUNT(ac.id) as count_ac,
            COALESCE(SUM(CASE WHEN ac.payment_mode = 2 THEN ac.total ELSE 0 END), 0) as cash_amt,
            COALESCE(SUM(CASE WHEN ac.payment_mode = 4 THEN ac.total ELSE 0 END), 0) as upi_amt,
            COALESCE(SUM(CASE WHEN ac.payment_mode = 3 THEN ac.total ELSE 0 END), 0) as cheque_amt,
            COALESCE(SUM(CASE WHEN ac.payment_mode = 5 THEN ac.total ELSE 0 END), 0) as neft_amt,
            COALESCE(SUM(CASE WHEN ac.payment_mode NOT IN (2, 3, 4, 5) THEN ac.total ELSE 0 END), 0) as other_amt
        FROM appointment_charges ac
        JOIN appointments a ON ac.appointment_id = a.id
        WHERE {ac_where_sql}
    """
    cursor.execute(ac_sql, ac_params)
    ac_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0)
    ac_gross = float(ac_row[0] or 0.0)
    ac_count = int(ac_row[1] or 0)
    ac_cash = float(ac_row[2] or 0.0)
    ac_upi = float(ac_row[3] or 0.0)
    ac_cheque = float(ac_row[4] or 0.0)
    ac_neft = float(ac_row[5] or 0.0)
    ac_other = float(ac_row[6] or 0.0)

    # 3. embryology_invoice
    ei_gross_expr = "(ei.payment_upi + ei.payment_cheque + ei.payment_neft + ei.payment_card_swipe)" if exclude_cash else "(ei.payment_cash + ei.payment_upi + ei.payment_cheque + ei.payment_neft + ei.payment_card_swipe)"
    ei_cash_expr = "0.0" if exclude_cash else "COALESCE(SUM(ei.payment_cash), 0)"
    ei_sql = f"""
        SELECT 
            COALESCE(SUM({ei_gross_expr}), 0) as gross_ei,
            COUNT(ei.id) as count_ei,
            {ei_cash_expr} as cash_amt,
            COALESCE(SUM(ei.payment_upi), 0) as upi_amt,
            COALESCE(SUM(ei.payment_cheque), 0) as cheque_amt,
            COALESCE(SUM(ei.payment_neft), 0) as neft_amt,
            COALESCE(SUM(ei.payment_card_swipe), 0) as other_amt
        FROM embryology_invoice ei
        WHERE {ei_where_sql}
    """
    cursor.execute(ei_sql, ei_params)
    ei_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0)
    ei_gross = float(ei_row[0] or 0.0)
    ei_count = int(ei_row[1] or 0)
    ei_cash = float(ei_row[2] or 0.0)
    ei_upi = float(ei_row[3] or 0.0)
    ei_cheque = float(ei_row[4] or 0.0)
    ei_neft = float(ei_row[5] or 0.0)
    ei_other = float(ei_row[6] or 0.0)

    # 4. income_manager
    # In node-backend / Laravel: 1=Cash, 2=Card/Swipe, 3=Cheque, 4=UPI, 5=NEFT
    im_cash_expr = "0.0" if exclude_cash else "COALESCE(SUM(CASE WHEN im.payment_method IN (1, 2) THEN im.amount ELSE 0 END), 0)"
    im_sql = f"""
        SELECT 
            COALESCE(SUM(im.amount), 0) as gross_im,
            COUNT(im.id) as count_im,
            {im_cash_expr} as cash_amt,
            COALESCE(SUM(CASE WHEN im.payment_method = 4 THEN im.amount ELSE 0 END), 0) as upi_amt,
            COALESCE(SUM(CASE WHEN im.payment_method = 3 THEN im.amount ELSE 0 END), 0) as cheque_amt,
            COALESCE(SUM(CASE WHEN im.payment_method = 5 THEN im.amount ELSE 0 END), 0) as neft_amt,
            COALESCE(SUM(CASE WHEN im.payment_method NOT IN (1, 2, 3, 4, 5) THEN im.amount ELSE 0 END), 0) as other_amt
        FROM income_manager im
        WHERE {im_where_sql}
    """
    cursor.execute(im_sql, im_params)
    im_row = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0)
    im_gross = float(im_row[0] or 0.0)
    im_count = int(im_row[1] or 0)
    im_cash = float(im_row[2] or 0.0)
    im_upi = float(im_row[3] or 0.0)
    im_cheque = float(im_row[4] or 0.0)
    im_neft = float(im_row[5] or 0.0)
    im_other = float(im_row[6] or 0.0)

    # --- 10 REVENUE STREAMS (Strict parity with node-backend reports/newCollectionReports & getAllCollectionReport) ---
    # 1. USG: appointments with appointment_charges.usg
    ac_usg_where = ["ac.usg IS NOT NULL", "ac.usg > 0"]
    ac_usg_params = []
    if start_date:
        ac_usg_where.append("a.date >= %s")
        ac_usg_params.append(start_date)
    if end_date:
        ac_usg_where.append("a.date <= %s")
        ac_usg_params.append(end_date)
    if branch_id:
        ac_usg_where.append("a.branch_id = %s")
        ac_usg_params.append(branch_id)
    if exclude_cash:
        ac_usg_where.append("ac.payment_mode != 2")

    cursor.execute(f"""
        SELECT COALESCE(SUM(ac.usg), 0), COUNT(a.id)
        FROM appointments a
        JOIN appointment_charges ac ON ac.appointment_id = a.id
        WHERE {" AND ".join(ac_usg_where)}
    """, ac_usg_params)
    usg_row = cursor.fetchone() or (0, 0)
    stream_usg = float(usg_row[0] or 0.0)
    stream_usg_cnt = int(usg_row[1] or 0)

    # 2. H.Inj: indoor_deposits charge_type = 1, case_type = 'Credit'
    hinj_where = ["d.is_deleted = 0", "d.case_type = 'Credit'", "d.charge_type = 1"]
    hinj_params = []
    if start_date:
        hinj_where.append("DATE(d.created_at) >= %s")
        hinj_params.append(start_date)
    if end_date:
        hinj_where.append("DATE(d.created_at) <= %s")
        hinj_params.append(end_date)
    if branch_id:
        hinj_where.append("d.branch_id = %s")
        hinj_params.append(branch_id)
    if exclude_cash:
        hinj_where.append("d.payment_type != 2")

    cursor.execute(f"""
        SELECT COALESCE(SUM(d.amount), 0), COUNT(d.id)
        FROM indoor_deposits d
        WHERE {" AND ".join(hinj_where)}
    """, hinj_params)
    hinj_row = cursor.fetchone() or (0, 0)
    stream_hinj = float(hinj_row[0] or 0.0)
    stream_hinj_cnt = int(hinj_row[1] or 0)

    # 3. IUI: indoor_deposits charge_type = 3, case_type = 'Credit'
    iui_where = ["d.is_deleted = 0", "d.case_type = 'Credit'", "d.charge_type = 3"]
    iui_params = []
    if start_date:
        iui_where.append("DATE(d.created_at) >= %s")
        iui_params.append(start_date)
    if end_date:
        iui_where.append("DATE(d.created_at) <= %s")
        iui_params.append(end_date)
    if branch_id:
        iui_where.append("d.branch_id = %s")
        iui_params.append(branch_id)
    if exclude_cash:
        iui_where.append("d.payment_type != 2")

    cursor.execute(f"""
        SELECT COALESCE(SUM(d.amount), 0), COUNT(d.id)
        FROM indoor_deposits d
        WHERE {" AND ".join(iui_where)}
    """, iui_params)
    iui_row = cursor.fetchone() or (0, 0)
    stream_iui = float(iui_row[0] or 0.0)
    stream_iui_cnt = int(iui_row[1] or 0)

    # 4. IVF: indoor_deposits charge_type = 2 (in node-backend getNewCollectionReport, 100 & 101 are excluded from standard IVF), case_type = 'Credit'
    ivf_where = ["d.is_deleted = 0", "d.case_type = 'Credit'", "d.charge_type = 2"]
    ivf_params = []
    if start_date:
        ivf_where.append("DATE(d.created_at) >= %s")
        ivf_params.append(start_date)
    if end_date:
        ivf_where.append("DATE(d.created_at) <= %s")
        ivf_params.append(end_date)
    if branch_id:
        ivf_where.append("d.branch_id = %s")
        ivf_params.append(branch_id)
    if exclude_cash:
        ivf_where.append("d.payment_type != 2")

    cursor.execute(f"""
        SELECT COALESCE(SUM(d.amount), 0), COUNT(d.id)
        FROM indoor_deposits d
        WHERE {" AND ".join(ivf_where)}
    """, ivf_params)
    ivf_row = cursor.fetchone() or (0, 0)
    stream_ivf = float(ivf_row[0] or 0.0)
    stream_ivf_cnt = int(ivf_row[1] or 0)

    # 5. OPD: In node-backend newCollectionReports, OPD charge amount = total - usg (category != 7)
    ac_opd_where = ["a.category_id IN (1, 2, 3, 4, 5, 6, 17, 18, 22)"]
    ac_opd_params = []
    if start_date:
        ac_opd_where.append("a.date >= %s")
        ac_opd_params.append(start_date)
    if end_date:
        ac_opd_where.append("a.date <= %s")
        ac_opd_params.append(end_date)
    if branch_id:
        ac_opd_where.append("a.branch_id = %s")
        ac_opd_params.append(branch_id)
    if payment_type:
        ac_opd_where.append("ac.payment_mode = %s")
        ac_opd_params.append(payment_type)
    elif exclude_cash:
        ac_opd_where.append("ac.payment_mode != 2")

    cursor.execute(f"""
        SELECT COALESCE(SUM(ac.total - COALESCE(ac.usg, 0)), 0), COUNT(ac.id)
        FROM appointments a
        JOIN appointment_charges ac ON ac.appointment_id = a.id
        WHERE {" AND ".join(ac_opd_where)}
    """, ac_opd_params)
    opd_row = cursor.fetchone() or (0, 0)
    stream_opd = float(opd_row[0] or 0.0)
    stream_opd_cnt = int(opd_row[1] or 0)

    # 6. IPD: Matches Candor getNewCollectionReport & getCollectionReportLaravelRaw exactly
    # Total IPD = Indoor Final Invoices (grand_total_amt) + Indoor Case Deposits (amount with charge_type = 4)
    
    # 6a. Indoor Final Settlement Invoices (indoor_books & indoor_invoices)
    ipd_inv_where = [
        "ib.is_final_invoice = 1",
        "ib.final_invoice_date IS NOT NULL",
        "(ib.is_medicare_patient IS NULL OR ib.is_medicare_patient = 0)",
        "(ib.is_pediatric_patient IS NULL OR ib.is_pediatric_patient = 0)"
    ]
    ipd_inv_params = []
    if start_date:
        ipd_inv_where.append("ib.final_invoice_date >= %s")
        ipd_inv_params.append(f"{start_date} 00:00:00")
    if end_date:
        ipd_inv_where.append("ib.final_invoice_date <= %s")
        ipd_inv_params.append(f"{end_date} 23:59:59")
    if branch_id:
        ipd_inv_where.append("ib.branch_id = %s")
        ipd_inv_params.append(branch_id)
    if payment_type:
        ipd_inv_where.append("ii.payment_mode = %s")
        ipd_inv_params.append(payment_type)
    elif exclude_cash:
        ipd_inv_where.append("ii.payment_mode != 2")

    cursor.execute(f"""
        SELECT 
            COALESCE(SUM(ii.grand_total_amt), 0),
            COUNT(ii.id)
        FROM indoor_books ib
        LEFT JOIN indoor_invoices ii ON ii.booking_id = ib.id
        WHERE {" AND ".join(ipd_inv_where)}
    """, ipd_inv_params)
    ipd_inv_row = cursor.fetchone() or (0, 0)
    ipd_inv_total = float(ipd_inv_row[0] or 0.0)
    ipd_inv_cnt = int(ipd_inv_row[1] or 0)

    # 6b. Indoor Case Deposits (Credit with charge_type = 4)
    ipd_dep_where = [
        "d.case_type = 'Credit'",
        "d.charge_type = 4",
        "(d.is_medicare IS NULL OR d.is_medicare = 0)",
        "(d.is_pediatric IS NULL OR d.is_pediatric = 0)"
    ]
    ipd_dep_params = []
    if start_date:
        ipd_dep_where.append("d.created_at >= %s")
        ipd_dep_params.append(f"{start_date} 00:00:00")
    if end_date:
        ipd_dep_where.append("d.created_at <= %s")
        ipd_dep_params.append(f"{end_date} 23:59:59")
    if branch_id:
        ipd_dep_where.append("d.branch_id = %s")
        ipd_dep_params.append(branch_id)
    if payment_type:
        ipd_dep_where.append("d.payment_type = %s")
        ipd_dep_params.append(payment_type)
    elif exclude_cash:
        ipd_dep_where.append("d.payment_type != 2")

    cursor.execute(f"""
        SELECT 
            COALESCE(SUM(d.amount), 0) AS net_ipd_collection,
            COUNT(d.id) AS credit_cnt
        FROM indoor_deposits d
        WHERE {" AND ".join(ipd_dep_where)}
    """, ipd_dep_params)
    ipd_dep_row = cursor.fetchone() or (0, 0)
    ipd_dep_total = float(ipd_dep_row[0] or 0.0)
    ipd_dep_cnt = int(ipd_dep_row[1] or 0)

    # Combined IPD = Invoices + Deposits
    stream_ipd = round(ipd_inv_total + ipd_dep_total, 2)
    stream_ipd_cnt = ipd_inv_cnt + ipd_dep_cnt

    # 7. O.Income: income_manager with type=1, status=1 (excluding pediatric, medicare, and inactive/other)
    im_stream_where = [
        "(ec.is_medicare IS NULL OR ec.is_medicare = 0)",
        "(ec.is_pediatric IS NULL OR ec.is_pediatric = 0)",
        "ec.type = 1",
        "ec.status = 1"
    ]
    im_stream_params = []
    if start_date:
        im_stream_where.append("DATE(im.date) >= %s")
        im_stream_params.append(start_date)
    if end_date:
        im_stream_where.append("DATE(im.date) <= %s")
        im_stream_params.append(end_date)
    if branch_id:
        im_stream_where.append("(im.branch_id = %s OR im.branch_id = %s)")
        im_stream_params.extend([branch_id, str(branch_id)])
    if exclude_cash:
        im_stream_where.append("im.payment_method != 1")

    cursor.execute(f"""
        SELECT COALESCE(SUM(im.amount), 0), COUNT(im.id)
        FROM income_manager im
        INNER JOIN expance_category ec ON ec.id = im.income_category
        WHERE {" AND ".join(im_stream_where)}
    """, im_stream_params)
    im_stream_row = cursor.fetchone() or (0, 0)
    stream_oinc = float(im_stream_row[0] or 0.0)
    stream_oinc_cnt = int(im_stream_row[1] or 0)

    # 8. Medicine Income: In newCollectionReports / reports.controller.js, medicineCollection comes from medicine_given_history (0)
    # or medication_patients_invoices if department_id=1. We query medicine_given_history first; if 0, check store
    med_hist_where = []
    med_hist_params = []
    if start_date:
        med_hist_where.append("DATE(given_date) >= %s")
        med_hist_params.append(start_date)
    if end_date:
        med_hist_where.append("DATE(given_date) <= %s")
        med_hist_params.append(end_date)
    if branch_id:
        med_hist_where.append("branch_id = %s")
        med_hist_params.append(branch_id)
    med_hist_sql = f"WHERE {' AND '.join(med_hist_where)}" if med_hist_where else ""

    cursor.execute(f"""
        SELECT COALESCE(SUM(total_amount), 0), COUNT(id)
        FROM medicine_given_history
        {med_hist_sql}
    """, med_hist_params)
    med_hist_row = cursor.fetchone() or (0, 0)
    stream_medicine = float(med_hist_row[0] or 0.0)
    stream_medicine_cnt = int(med_hist_row[1] or 0)

    # 9. Embryology Income
    stream_emb = round(ei_gross, 2)
    stream_emb_cnt = ei_count

    # Combined Healthcare Aggregates (Healthcare Total = sum of clinical streams + O.Income)
    combined_hc_gross = round(hc_gross + ac_gross + ei_gross + stream_oinc, 2)
    combined_hc_credit_count = hc_credit_count + ac_count + ei_count + stream_oinc_cnt
    combined_hc_cash = round(hc_cash + ac_cash + ei_cash + im_cash, 2)
    combined_hc_upi = round(hc_upi + ac_upi + ei_upi + im_upi, 2)
    combined_hc_cheque = round(hc_cheque + ac_cheque + ei_cheque + im_cheque, 2)
    combined_hc_neft = round(hc_neft + ac_neft + ei_neft + im_neft, 2)
    combined_hc_other = round(hc_other + ac_other + ei_other + im_other, 2)

    # --- EXECUTE PHARMACY COLLECTION AGGREGATE (Sales Register: mpi) ---
    # Without GST: mpi.sell_price_without_gst
    # With GST: mpi.sell_price
    if exclude_gst:
        if exclude_cash:
            ph_sales_metric = "mpi.payment_upi * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0)) + mpi.payment_cheque * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0)) + mpi.payment_neft * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        else:
            ph_sales_metric = "mpi.sell_price_without_gst"
        ph_cash_metric = "0.0" if exclude_cash else "mpi.payment_cash * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        ph_upi_metric = "mpi.payment_upi * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        ph_cheque_metric = "mpi.payment_cheque * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
        ph_neft_metric = "mpi.payment_neft * (mpi.sell_price_without_gst / NULLIF(mpi.sell_price, 0))"
    else:
        if exclude_cash:
            ph_sales_metric = "(mpi.payment_upi + mpi.payment_cheque + mpi.payment_neft)"
        else:
            ph_sales_metric = "mpi.sell_price"
        ph_cash_metric = "0.0" if exclude_cash else "mpi.payment_cash"
        ph_upi_metric = "mpi.payment_upi"
        ph_cheque_metric = "mpi.payment_cheque"
        ph_neft_metric = "mpi.payment_neft"

    ph_sql = f"""
        SELECT 
            COALESCE(SUM({ph_sales_metric}), 0) as total_pharmacy,
            COUNT(DISTINCT mpi.id) as count_pharmacy,
            COALESCE(SUM({ph_cash_metric}), 0) as cash_amt,
            COALESCE(SUM({ph_upi_metric}), 0) as upi_amt,
            COALESCE(SUM({ph_cheque_metric}), 0) as cheque_amt,
            COALESCE(SUM({ph_neft_metric}), 0) as neft_amt
        FROM medication_patients_invoices mpi
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

    # --- EXECUTE PHARMACY RETURN AGGREGATE (Sales Return Register: msc) ---
    # Without GST: msc.price_without_gst
    # With GST: msc.payable_amount
    if exclude_gst:
        if exclude_cash:
            pr_sales_metric = "msc.payment_upi * (msc.price_without_gst / NULLIF(msc.payable_amount, 0)) + msc.payment_cheque * (msc.price_without_gst / NULLIF(msc.payable_amount, 0)) + msc.payment_neft * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        else:
            pr_sales_metric = "msc.price_without_gst"
        pr_cash_metric = "0.0" if exclude_cash else "msc.payment_cash * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        pr_upi_metric = "msc.payment_upi * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        pr_cheque_metric = "msc.payment_cheque * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
        pr_neft_metric = "msc.payment_neft * (msc.price_without_gst / NULLIF(msc.payable_amount, 0))"
    else:
        if exclude_cash:
            pr_sales_metric = "(msc.payment_upi + msc.payment_cheque + msc.payment_neft)"
        else:
            pr_sales_metric = "msc.payable_amount"
        pr_cash_metric = "0.0" if exclude_cash else "msc.payment_cash"
        pr_upi_metric = "msc.payment_upi"
        pr_cheque_metric = "msc.payment_cheque"
        pr_neft_metric = "msc.payment_neft"

    pr_sql = f"""
        SELECT 
            COALESCE(SUM({pr_sales_metric}), 0) as total_return,
            COUNT(DISTINCT msc.id) as count_return,
            COALESCE(SUM({pr_cash_metric}), 0) as cash_amt,
            COALESCE(SUM({pr_upi_metric}), 0) as upi_amt,
            COALESCE(SUM({pr_cheque_metric}), 0) as cheque_amt,
            COALESCE(SUM({pr_neft_metric}), 0) as neft_amt
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
    # 2. Total Healthcare Collection (Indoor deposits + OPD + Embryology + Income Manager)
    total_healthcare_collection = combined_hc_gross
    # 3. Total Pharmacy Collection (Net = Sales Register - Sales Return Register)
    total_pharmacy_collection = round(ph_gross - pr_return, 2)
    # 1. Total Collection (Gross Combined Collection = Total Healthcare Collection + Total Pharmacy Collection)
    total_gross_collection = round(total_healthcare_collection + total_pharmacy_collection, 2)
    # 4. PAYMENT RETURN (Hospital Refund/Debit + Pharmacy Credit Note/Sales Return Register)
    total_payment_return = round(hc_return + pr_return, 2)
    # 5. Collection (Net Final In-Hand Collection)
    # Total Pharmacy Collection is ALREADY net of pharmacy return (ph_gross - pr_return).
    # Therefore, Net Collection = Total Healthcare Collection + Total Pharmacy Collection - Healthcare Return (do NOT double-deduct pharmacy return).
    net_collection = round(total_healthcare_collection + total_pharmacy_collection - hc_return, 2)

    # Payment modes summary (Net)
    total_cash_net = 0.0 if exclude_cash else round(max(0.0, (combined_hc_cash + ph_cash) - pr_cash), 2)
    total_upi_net = round(max(0.0, (combined_hc_upi + ph_upi) - pr_upi), 2)
    total_cheque_net = round(max(0.0, (combined_hc_cheque + ph_cheque) - pr_cheque), 2)
    total_neft_net = round(max(0.0, (combined_hc_neft + ph_neft) - pr_neft), 2)
    total_other_net = round(combined_hc_other, 2)

    # --- MONTHLY TRENDS ---
    # 1. Monthly indoor deposits
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

    # 2. Monthly appointment charges
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(a.date, '%%Y-%%m') as ym,
            COALESCE(SUM(ac.total), 0) as gross_ac
        FROM appointment_charges ac
        JOIN appointments a ON ac.appointment_id = a.id
        WHERE {ac_where_sql} AND a.date IS NOT NULL
        GROUP BY ym
    """, ac_params)
    for r in cursor.fetchall():
        ym, amt = r[0], float(r[1] or 0)
        if ym not in hc_monthly:
            hc_monthly[ym] = {"gross_hc": 0.0, "return_hc": 0.0}
        hc_monthly[ym]["gross_hc"] += amt

    # 3. Monthly embryology invoice (parity with invoice voucher date)
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT({ei_date_col}, '%%Y-%%m') as ym,
            COALESCE(SUM({ei_gross_expr}), 0) as gross_ei
        FROM embryology_invoice ei
        WHERE {ei_where_sql} AND {ei_date_col} IS NOT NULL
        GROUP BY ym
    """, ei_params)
    for r in cursor.fetchall():
        ym, amt = r[0], float(r[1] or 0)
        if ym not in hc_monthly:
            hc_monthly[ym] = {"gross_hc": 0.0, "return_hc": 0.0}
        hc_monthly[ym]["gross_hc"] += amt

    # Monthly pharmacy (Sales Register: mpi)
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(mpi.date_of_transaction, '%%Y-%%m') as ym,
            COALESCE(SUM({ph_sales_metric}), 0) as gross_ph
        FROM medication_patients_invoices mpi
        WHERE {ph_where_sql} AND mpi.date_of_transaction IS NOT NULL
        GROUP BY ym
        ORDER BY ym ASC
    """, ph_params)
    ph_monthly = {r[0]: float(r[1] or 0) for r in cursor.fetchall()}

    # Monthly pharmacy return (Sales Return Register: msc)
    cursor.execute(f"""
        SELECT 
            DATE_FORMAT(msc.date_of_transaction, '%%Y-%%m') as ym,
            COALESCE(SUM({pr_sales_metric}), 0) as return_ph
        FROM medication_sales_credit msc
        WHERE {pr_where_sql} AND msc.date_of_transaction IS NOT NULL
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
            "pharmacy_collection": round(gph - rph, 2),
            "payment_return": round(tot_ret, 2)
        })

    # --- BRANCH BREAKDOWN ---
    cursor.execute("""
        SELECT id, name FROM branch WHERE status = 1 OR id IN (SELECT DISTINCT branch_id FROM indoor_deposits) ORDER BY name
    """)
    all_branch_rows = cursor.fetchall()
    branches = [{"id": b[0], "name": b[1]} for b in all_branch_rows]

    # Branch aggregations across all clinical tables (Indoor + OPD + Embryology) + pharmacy sales + pharmacy return
    branch_stats_sql = f"""
        SELECT 
            b.id,
            b.name,
            (COALESCE(hc.gross_hc, 0) + COALESCE(ac.gross_ac, 0) + COALESCE(ei.gross_ei, 0)) as gross_hc,
            COALESCE(hc.return_hc, 0) as return_hc,
            COALESCE(ph.gross_ph, 0) as gross_ph,
            COALESCE(pr.return_ph, 0) as return_ph
        FROM branch b
        LEFT JOIN (
            SELECT CAST(branch_id AS UNSIGNED) as b_id,
                   SUM(CASE WHEN case_type = 'Credit' THEN amount ELSE 0 END) as gross_hc,
                   SUM(CASE WHEN case_type = 'Debit' THEN amount ELSE 0 END) as return_hc
            FROM indoor_deposits d
            WHERE {hc_where_sql}
            GROUP BY b_id
        ) hc ON hc.b_id = b.id
        LEFT JOIN (
            SELECT CAST(a.branch_id AS UNSIGNED) as b_id,
                   SUM(ac.total) as gross_ac
            FROM appointment_charges ac
            JOIN appointments a ON ac.appointment_id = a.id
            WHERE {ac_where_sql}
            GROUP BY b_id
        ) ac ON ac.b_id = b.id
        LEFT JOIN (
            SELECT CAST(ei.branch_id AS UNSIGNED) as b_id,
                   SUM({ei_gross_expr}) as gross_ei
            FROM embryology_invoice ei
            WHERE {ei_where_sql}
            GROUP BY b_id
        ) ei ON ei.b_id = b.id
        LEFT JOIN (
            SELECT CAST(mpi.branch_id AS UNSIGNED) as b_id,
                   COALESCE(SUM({ph_sales_metric}), 0) as gross_ph
            FROM medication_patients_invoices mpi
            WHERE {ph_where_sql}
            GROUP BY b_id
        ) ph ON ph.b_id = b.id
        LEFT JOIN (
            SELECT CAST(branch_id AS UNSIGNED) as b_id,
                   COALESCE(SUM({pr_sales_metric}), 0) as return_ph
            FROM medication_sales_credit msc
            WHERE {pr_where_sql}
            GROUP BY b_id
        ) pr ON pr.b_id = b.id
        HAVING (gross_hc > 0 OR gross_ph > 0 OR return_hc > 0 OR return_ph > 0)
        ORDER BY (gross_hc + gross_ph) DESC
    """
    combined_params = hc_params + ac_params + ei_params + ph_params + pr_params
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

    # --- RECENT TRANSACTIONS LEDGER ---
    records = []
    
    # 1. Healthcare Indoor Deposits (Credits & Debits)
    hc_rec_query = f"""
        SELECT 
            d.id,
            d.created_at,
            'Healthcare (Deposit)' as source,
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
        LIMIT 60
    """
    cursor.execute(hc_rec_query, hc_params)
    for r in cursor.fetchall():
        is_ret = (str(r[3]).strip().lower() == "debit")
        records.append({
            "id": f"HC-{r[0]}",
            "date": r[1].strftime("%Y-%m-%d %H:%M") if r[1] else "-",
            "source": "Healthcare (Deposit)" if not is_ret else "Healthcare Return",
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

    # 2. Appointment Charges (OPD / Consultation)
    ac_rec_query = f"""
        SELECT 
            ac.id,
            a.date,
            'OPD / Consultation' as source,
            'Credit' as case_type,
            ac.total as amount,
            p.id as patient_id,
            p.code as patient_code,
            CONCAT(IFNULL(p.name, ''), ' ', IFNULL(p.surname, '')) as patient_name,
            IFNULL(b.name, CONCAT('Branch ', a.branch_id)) as branch_name,
            CASE ac.payment_mode
                WHEN 2 THEN 'Cash'
                WHEN 4 THEN 'UPI'
                WHEN 3 THEN 'Cheque'
                WHEN 5 THEN 'NEFT/RTGS'
                WHEN 1 THEN 'Card/Swipe'
                ELSE 'Other'
            END as mode_str,
            COALESCE(ac.invoice_no, ac.detail, 'OPD Charge') as reference_note
        FROM appointment_charges ac
        JOIN appointments a ON ac.appointment_id = a.id
        LEFT JOIN patients p ON a.patients_id = p.id
        LEFT JOIN branch b ON a.branch_id = b.id
        WHERE {ac_where_sql}
        ORDER BY a.date DESC, ac.id DESC
        LIMIT 50
    """
    cursor.execute(ac_rec_query, ac_params)
    for r in cursor.fetchall():
        records.append({
            "id": f"OPD-{r[0]}",
            "date": r[1].strftime("%Y-%m-%d") if r[1] else "-",
            "source": "OPD / Consultation",
            "source_type": "healthcare",
            "is_return": False,
            "amount": float(r[4] or 0),
            "patient_id": r[5],
            "patient_code": r[6] or "-",
            "patient_name": (r[7] or "").strip() or "OPD Patient",
            "branch_name": r[8] or "-",
            "payment_mode": r[9] or "Cash",
            "reference": r[10] or "-"
        })

    # 3. Embryology / Andrology Invoices
    ei_rec_query = f"""
        SELECT 
            ei.id,
            {ei_date_col} as tr_date,
            'Embryology' as source,
            'Credit' as case_type,
            ({ei_gross_expr}) as amount,
            p.id as patient_id,
            p.code as patient_code,
            CONCAT(IFNULL(p.name, ''), ' ', IFNULL(p.surname, '')) as patient_name,
            IFNULL(b.name, CONCAT('Branch ', ei.branch_id)) as branch_name,
            CASE 
                WHEN ei.payment_upi > 0 THEN 'UPI'
                WHEN ei.payment_cash > 0 THEN 'Cash'
                WHEN ei.payment_cheque > 0 THEN 'Cheque'
                WHEN ei.payment_neft > 0 THEN 'NEFT/RTGS'
                WHEN ei.payment_card_swipe > 0 THEN 'Card/Swipe'
                ELSE 'Cash'
            END as mode_str,
            COALESCE(ei.process_name, 'Embryology Invoice') as reference_note
        FROM embryology_invoice ei
        LEFT JOIN patients p ON ei.patients_id = p.id
        LEFT JOIN branch b ON ei.branch_id = b.id
        WHERE {ei_where_sql}
        ORDER BY tr_date DESC, ei.id DESC
        LIMIT 40
    """
    cursor.execute(ei_rec_query, ei_params)
    for r in cursor.fetchall():
        records.append({
            "id": f"EMB-{r[0]}",
            "date": r[1].strftime("%Y-%m-%d %H:%M") if hasattr(r[1], "strftime") else (str(r[1]) if r[1] else "-"),
            "source": "Embryology / Andrology",
            "source_type": "healthcare",
            "is_return": False,
            "amount": float(r[4] or 0),
            "patient_id": r[5],
            "patient_code": r[6] or "-",
            "patient_name": (r[7] or "").strip() or "Lab Patient",
            "branch_name": r[8] or "-",
            "payment_mode": r[9] or "Cash",
            "reference": r[10] or "-"
        })

    # 4. Pharmacy Returns (Medication Sales Credit)
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
        LIMIT 60
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

    # Total Income = USG + H.Inj + IUI + IVF + OPD + IPD + O.Income + Medicine Income + Embryology Income
    total_income_amount = round(
        stream_usg + stream_hinj + stream_iui + stream_ivf + stream_opd +
        stream_ipd + stream_oinc + stream_medicine + stream_emb,
        2
    )

    categories_breakdown = [
        {"key": "USG", "name": "USG", "amount": stream_usg, "count": stream_usg_cnt, "icon": "📡", "color": "#0284C7"},
        {"key": "H_INJ", "name": "H.Inj", "amount": stream_hinj, "count": stream_hinj_cnt, "icon": "💉", "color": "#10B981"},
        {"key": "IUI", "name": "IUI", "amount": stream_iui, "count": stream_iui_cnt, "icon": "🔬", "color": "#F59E0B"},
        {"key": "IVF", "name": "IVF", "amount": stream_ivf, "count": stream_ivf_cnt, "icon": "🧬", "color": "#8B5CF6"},
        {"key": "OPD", "name": "OPD", "amount": stream_opd, "count": stream_opd_cnt, "icon": "🩺", "color": "#06B6D4"},
        {"key": "IPD", "name": "IPD", "amount": stream_ipd, "count": stream_ipd_cnt, "icon": "🛏️", "color": "#EC4899"},
        {"key": "O_INCOME", "name": "O.Income", "amount": stream_oinc, "count": stream_oinc_cnt, "icon": "📈", "color": "#F97316"},
        {"key": "MEDICINE", "name": "Medicine Income", "amount": stream_medicine, "count": stream_medicine_cnt, "icon": "💊", "color": "#14B8A6"},
        {"key": "EMBRYOLOGY", "name": "Embryology Income", "amount": stream_emb, "count": stream_emb_cnt, "icon": "🧪", "color": "#6366F1"},
        {"key": "TOTAL_INCOME", "name": "Total Income", "amount": total_income_amount, "count": stream_usg_cnt + stream_hinj_cnt + stream_iui_cnt + stream_ivf_cnt + stream_opd_cnt + stream_ipd_cnt + stream_oinc_cnt + stream_medicine_cnt + stream_emb_cnt, "icon": "💎", "color": "#0F172A"}
    ]

    # Total Healthcare Collection = Total Income from all departmental healthcare streams (reports/newCollectionReports)
    total_healthcare_collection = total_income_amount
    # Total Collection (Gross) = Total Healthcare Collection + Total Pharmacy Collection
    total_gross_collection = round(total_healthcare_collection + total_pharmacy_collection, 2)
    # Total Pharmacy Collection is ALREADY net of pharmacy return (ph_gross - pr_return).
    # Net In-Hand Collection = Total Healthcare Collection + Total Pharmacy Collection - Healthcare Return
    net_collection = round(total_healthcare_collection + total_pharmacy_collection - hc_return, 2)

    return JsonResponse({
        "status": "success",
        "exclude_gst": 1 if exclude_gst else 0,
        "summary": {
            "net_collection": net_collection,
            "total_collection": total_gross_collection,
            "total_healthcare_collection": total_healthcare_collection,
            "total_pharmacy_collection": total_pharmacy_collection,
            "payment_return": total_payment_return,
            "healthcare_return": round(hc_return, 2),
            "pharmacy_return": round(pr_return, 2),
            "total_income": total_income_amount,
            "categories_breakdown": categories_breakdown,
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
            "source": source_filter,
            "exclude_gst": 1 if exclude_gst else 0,
            "exclude_cash": 1 if exclude_cash else 0
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



def opd_analytics_api(request):
    """
    Live OPD Report Analytics API:
    - Total Appointments booked
    - Attended OPD (is_done = 1)
    - Not Attended / No-Show (is_done = 0)
    - Category breakdown (from category table)
    - Branch breakdown
    - Daily trend
    - Patient-level list with status, category, branch, arrival time
    """
    from django.db import connection
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    branch_id = request.GET.get('branch_id', '').strip()
    category_id = request.GET.get('category_id', '').strip()
    status_filter = request.GET.get('status', '').strip()
    search_q = request.GET.get('search', '').strip()

    where_clauses = ['a.deleted_at IS NULL']
    params = []

    from datetime import date
    today = date.today()
    default_start = today.strftime('%Y-%m-01')
    default_end = today.strftime('%Y-%m-%d')

    if start_date:
        where_clauses.append('a.date >= %s')
        params.append(start_date)
    else:
        where_clauses.append('a.date >= %s')
        params.append(default_start)

    if end_date:
        where_clauses.append('a.date <= %s')
        params.append(end_date)
    else:
        where_clauses.append('a.date <= %s')
        params.append(default_end)

    if branch_id:
        where_clauses.append('a.branch_id = %s')
        params.append(branch_id)

    if category_id:
        where_clauses.append('a.category_id = %s')
        params.append(category_id)

    if status_filter == 'attended':
        where_clauses.append('a.is_done = 1')
    elif status_filter == 'not_attended':
        where_clauses.append('a.is_done = 0')

    # Exclude IVF donors (when category is IVF and patient is_donor = 1)
    where_clauses.append('NOT (CAST(a.category_id AS UNSIGNED) IN (1, 2, 11, 14, 50) AND COALESCE(p.is_donor, 0) = 1)')

    where_sql = ' AND '.join(where_clauses)
    cursor = connection.cursor()

    # Deduplicate same-day visits (Option B: 1 visit per patient per day)
    summary_sql = f"""
        SELECT 
            COUNT(*) as total_daily_visits,
            SUM(CASE WHEN v.visit_done = 1 THEN 1 ELSE 0 END) as attended_count,
            SUM(CASE WHEN v.visit_done = 0 THEN 1 ELSE 0 END) as not_attended_count,
            SUM(CASE WHEN v.is_core = 1 THEN 1 ELSE 0 END) as core_cat_total,
            SUM(CASE WHEN v.is_core = 1 AND v.visit_done = 1 THEN 1 ELSE 0 END) as core_cat_attended,
            SUM(CASE WHEN v.is_core = 1 AND v.visit_done = 0 THEN 1 ELSE 0 END) as core_cat_not_attended
        FROM (
            SELECT 
                a.patients_id, 
                a.date,
                MAX(a.is_done) as visit_done,
                MAX(CASE WHEN CAST(a.category_id AS UNSIGNED) IN (1, 2, 3, 4, 5, 6, 17, 18) THEN 1 ELSE 0 END) as is_core
            FROM appointments a
            LEFT JOIN patients p ON a.patients_id = p.id
            WHERE {where_sql}
            GROUP BY a.patients_id, a.date
        ) v
    """
    cursor.execute(summary_sql, params)
    s_row = cursor.fetchone()
    total_appts = int(s_row[0] or 0)
    attended_count = int(s_row[1] or 0)
    not_attended_count = int(s_row[2] or 0)
    core_cat_total = int(s_row[3] or 0)
    core_cat_attended = int(s_row[4] or 0)
    core_cat_not_attended = int(s_row[5] or 0)
    attendance_rate = round((attended_count / total_appts * 100), 1) if total_appts > 0 else 0
    no_show_rate = round((not_attended_count / total_appts * 100), 1) if total_appts > 0 else 0

    # Category breakdown (deduplicated per patient per date)
    cat_sql = f"""
        SELECT 
            COALESCE(c.id, 0) as category_id,
            COALESCE(c.name, 'Unassigned') as category_name,
            COUNT(*) as total_count,
            SUM(CASE WHEN v.visit_done = 1 THEN 1 ELSE 0 END) as attended_count,
            SUM(CASE WHEN v.visit_done = 0 THEN 1 ELSE 0 END) as not_attended_count
        FROM (
            SELECT 
                a.patients_id,
                a.date,
                a.category_id,
                MAX(a.is_done) as visit_done
            FROM appointments a
            LEFT JOIN patients p ON a.patients_id = p.id
            WHERE {where_sql}
            GROUP BY a.patients_id, a.date, a.category_id
        ) v
        LEFT JOIN category c ON CAST(v.category_id AS UNSIGNED) = c.id
        GROUP BY c.id, c.name
        ORDER BY total_count DESC
    """
    cursor.execute(cat_sql, params)
    categories = []
    for r in cursor.fetchall():
        c_tot = int(r[2] or 0)
        c_att = int(r[3] or 0)
        c_not = int(r[4] or 0)
        categories.append({
            'category_id': r[0],
            'category_name': r[1],
            'total_appointments': c_tot,
            'attended': c_att,
            'not_attended': c_not,
            'attendance_rate': round((c_att / c_tot * 100), 1) if c_tot > 0 else 0,
            'no_show_rate': round((c_not / c_tot * 100), 1) if c_tot > 0 else 0,
        })

    # Branch breakdown (deduplicated per patient per date)
    branch_sql = f"""
        SELECT 
            COALESCE(b.id, 0) as branch_id,
            COALESCE(b.name, 'Unassigned') as branch_name,
            COUNT(*) as total_count,
            SUM(CASE WHEN v.visit_done = 1 THEN 1 ELSE 0 END) as attended_count,
            SUM(CASE WHEN v.visit_done = 0 THEN 1 ELSE 0 END) as not_attended_count
        FROM (
            SELECT 
                a.patients_id,
                a.date,
                a.branch_id,
                MAX(a.is_done) as visit_done
            FROM appointments a
            LEFT JOIN patients p ON a.patients_id = p.id
            WHERE {where_sql}
            GROUP BY a.patients_id, a.date, a.branch_id
        ) v
        LEFT JOIN branch b ON v.branch_id = b.id
        GROUP BY b.id, b.name
        ORDER BY total_count DESC
    """
    cursor.execute(branch_sql, params)
    branches = []
    for r in cursor.fetchall():
        b_tot = int(r[2] or 0)
        b_att = int(r[3] or 0)
        b_not = int(r[4] or 0)
        branches.append({
            'branch_id': r[0],
            'branch_name': r[1],
            'total_appointments': b_tot,
            'attended': b_att,
            'not_attended': b_not,
            'attendance_rate': round((b_att / b_tot * 100), 1) if b_tot > 0 else 0,
            'no_show_rate': round((b_not / b_tot * 100), 1) if b_tot > 0 else 0,
        })

    # Daily trend (deduplicated per patient per date)
    daily_sql = f"""
        SELECT 
            v.date,
            COUNT(*) as total_count,
            SUM(CASE WHEN v.visit_done = 1 THEN 1 ELSE 0 END) as attended_count,
            SUM(CASE WHEN v.visit_done = 0 THEN 1 ELSE 0 END) as not_attended_count
        FROM (
            SELECT 
                a.patients_id,
                a.date,
                MAX(a.is_done) as visit_done
            FROM appointments a
            LEFT JOIN patients p ON a.patients_id = p.id
            WHERE {where_sql}
            GROUP BY a.patients_id, a.date
        ) v
        GROUP BY v.date
        ORDER BY v.date ASC
    """
    cursor.execute(daily_sql, params)
    daily_trend = []
    for r in cursor.fetchall():
        d_tot = int(r[1] or 0)
        d_att = int(r[2] or 0)
        d_not = int(r[3] or 0)
        daily_trend.append({
            'date': str(r[0]),
            'total_appointments': d_tot,
            'attended': d_att,
            'not_attended': d_not
        })

    patient_where = list(where_clauses)
    patient_params = list(params)
    if search_q:
        patient_where.append("(p.name LIKE %s OR p.surname LIKE %s OR p.code LIKE %s OR p.mobile_number LIKE %s)")
        patient_params.extend([f'%{search_q}%', f'%{search_q}%', f'%{search_q}%', f'%{search_q}%'])

    patient_where_sql = ' AND '.join(patient_where)
    # Deduplicate same patient same date in the patient list as well
    patient_sql = f"""
        SELECT 
            MAX(a.id) as id,
            a.date,
            MAX(a.time) as time,
            MAX(a.arrival_time) as arrival_time,
            MAX(a.is_done) as is_done,
            p.code,
            p.name,
            p.surname,
            p.mobile_number,
            MAX(c.name) as category_name,
            MAX(b.name) as branch_name
        FROM appointments a
        LEFT JOIN patients p ON a.patients_id = p.id
        LEFT JOIN category c ON CAST(a.category_id AS UNSIGNED) = c.id
        LEFT JOIN branch b ON a.branch_id = b.id
        WHERE {patient_where_sql}
        GROUP BY a.patients_id, a.date, p.code, p.name, p.surname, p.mobile_number
        ORDER BY a.date DESC, MAX(a.time) DESC, MAX(a.id) DESC
        LIMIT 200
    """
    cursor.execute(patient_sql, patient_params)
    patients_data = []
    for r in cursor.fetchall():
        full_name = f"{r[6] or ''} {r[7] or ''}".strip() or 'Unknown Patient'
        patients_data.append({
            'appointment_id': r[0],
            'date': str(r[1]) if r[1] else '',
            'time': str(r[2]) if r[2] else '-',
            'arrival_time': str(r[3]) if r[3] else '-',
            'status': 'Attended' if r[4] == 1 else 'Not Attended',
            'is_done': r[4],
            'code': r[5] or '-',
            'patient_name': full_name,
            'mobile': r[8] or '-',
            'category': r[9] or 'Unassigned',
            'branch': r[10] or 'Main Branch'
        })

    cursor.execute('SELECT id, name FROM branch WHERE status = 1 ORDER BY name')
    branch_options = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]
    cursor.execute('SELECT id, name FROM category WHERE status = 1 ORDER BY name')
    category_options = [{'id': r[0], 'name': r[1]} for r in cursor.fetchall()]

    return JsonResponse({
        'status': 'success',
        'summary': {
            'total_appointments': total_appts,
            'attended_opd': attended_count,
            'not_attended': not_attended_count,
            'core_cat_total': core_cat_total,
            'core_cat_attended': core_cat_attended,
            'core_cat_not_attended': core_cat_not_attended,
            'attendance_rate': attendance_rate,
            'no_show_rate': no_show_rate
        },
        'categories': categories,
        'branches': branches,
        'daily_trend': daily_trend,
        'patients': patients_data,
        'filters': {
            'branches': branch_options,
            'categories': category_options
        }
    })
