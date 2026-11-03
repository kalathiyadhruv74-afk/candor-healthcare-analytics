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
from .db_utils import (
    with_db_safety,
    get_branch_options,
    get_category_options,
    get_donor_patient_ids,
    close_db,
)

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
    try:
        branches = get_branch_options()
        categories = get_category_options()
    except Exception:
        branches, categories = [], []
    finally:
        close_db()
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

@with_db_safety(cache_prefix="ivf_booking", cache_ttl=40, heavy=True)
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
        patient_name = row[3].strip() if row[3] else "Unknown Patient"

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

@with_db_safety(cache_prefix="pharmacy", cache_ttl=40, heavy=True)
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

@with_db_safety(cache_prefix="collection", cache_ttl=40, heavy=True)
def collection_analytics_api(request):
    """Unified Collection report — few SELECTs + Python aggregation."""
    from .collection_report_engine import build_collection_report
    start_date = request.GET.get("start_date", "2026-01-01").strip()
    end_date = request.GET.get("end_date", "").strip()
    branch_id = request.GET.get("branch_id", "").strip()
    source_filter = request.GET.get("source", "").strip().lower()
    exclude_gst = request.GET.get("exclude_gst", "1").strip() == "1"
    exclude_cash = request.GET.get("exclude_cash", "0").strip() in ("1", "true", "yes")
    payment_type = request.GET.get("payment_type", "").strip()
    try:
        payload = build_collection_report(
            start_date=start_date,
            end_date=end_date,
            branch_id=branch_id,
            source_filter=source_filter,
            exclude_gst=exclude_gst,
            exclude_cash=exclude_cash,
            payment_type=payment_type,
        )
        return JsonResponse(payload)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


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

@with_db_safety(cache_prefix="anc_patients", cache_ttl=60, heavy=True)
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

        full_name = r[2].strip() if r[2] else "Unknown Patient"

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



@with_db_safety(cache_prefix="opd", cache_ttl=30, heavy=True)
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

    from datetime import date
    today = date.today()
    if not start_date:
        start_date = today.strftime('%Y-%m-01')
    if not end_date:
        end_date = today.strftime('%Y-%m-%d')

    # Metadata from short TTL cache (avoids extra MySQL hits per concurrent user)
    branch_options = get_branch_options()
    category_options = get_category_options()
    branch_dict = {b['id']: b['name'] for b in branch_options}
    cat_dict = {c['id']: c['name'] for c in category_options}
    donor_pids = get_donor_patient_ids()

    cursor = connection.cursor()

    # 2. Build indexed appointments query (without expensive JOINs or temp tables on DB)
    # Exclude placeholder follow-up slots that have no scheduled time, no arrival time, and were never attended
    appt_where = ['a.deleted_at IS NULL', 'NOT (a.time IS NULL AND a.arrival_time IS NULL AND a.is_done = 0)']
    appt_params = []
    if start_date:
        appt_where.append('a.date >= %s')
        appt_params.append(start_date)
    if end_date:
        appt_where.append('a.date <= %s')
        appt_params.append(end_date)
    if branch_id:
        appt_where.append('a.branch_id = %s')
        appt_params.append(branch_id)
    if category_id:
        appt_where.append('a.category_id = %s')
        appt_params.append(category_id)
    if status_filter == 'attended':
        appt_where.append('a.is_done = 1')
    elif status_filter == 'not_attended':
        appt_where.append('a.is_done = 0')

    appt_where_sql = ' AND '.join(appt_where)

    # Fast indexed scan on appointments
    query = f"""
        SELECT 
            a.id,
            a.patients_id,
            a.date,
            a.time,
            a.arrival_time,
            a.is_done,
            CAST(a.branch_id AS UNSIGNED) as branch_id,
            CAST(a.category_id AS UNSIGNED) as category_id
        FROM appointments a
        WHERE {appt_where_sql}
        ORDER BY a.date DESC, a.time DESC, a.id DESC
    """
    cursor.execute(query, appt_params)
    rows = cursor.fetchall()

    from collections import defaultdict
    from datetime import datetime, timedelta

    ivf_categories = {1, 2, 11, 14, 50}
    core_categories = {1, 2, 3, 4, 5, 6, 17, 18}

    def _norm_date(value):
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        s = str(value).strip()
        return s[:10] if len(s) >= 10 else s

    # Count every valid appointment (not unique-patient collapse) for proper daily totals
    cat_stats = defaultdict(lambda: {'total': 0, 'attended': 0, 'not_attended': 0})
    br_stats = defaultdict(lambda: {'total': 0, 'attended': 0, 'not_attended': 0})
    daily_stats = defaultdict(lambda: {'total': 0, 'attended': 0, 'not_attended': 0})
    filtered_appts_for_patient_table = []

    total_appts = 0
    attended_count = 0
    not_attended_count = 0
    core_cat_total = 0
    core_cat_attended = 0

    for r in rows:
        aid, pid, adate, atime, arr_time, is_done, bid, cid = r
        # Exclude IVF donor visits
        if cid in ivf_categories and pid in donor_pids:
            continue

        is_done_bool = (int(is_done or 0) == 1)
        adate_str = _norm_date(adate)
        if not adate_str:
            continue

        bid = int(bid or 0)
        cid = int(cid or 0)
        is_core = cid in core_categories

        total_appts += 1
        if is_done_bool:
            attended_count += 1
        else:
            not_attended_count += 1

        if is_core:
            core_cat_total += 1
            if is_done_bool:
                core_cat_attended += 1

        cat_stats[cid]['total'] += 1
        br_stats[bid]['total'] += 1
        daily_stats[adate_str]['total'] += 1
        if is_done_bool:
            cat_stats[cid]['attended'] += 1
            br_stats[bid]['attended'] += 1
            daily_stats[adate_str]['attended'] += 1
        else:
            cat_stats[cid]['not_attended'] += 1
            br_stats[bid]['not_attended'] += 1
            daily_stats[adate_str]['not_attended'] += 1

        filtered_appts_for_patient_table.append({
            'id': aid,
            'pid': pid,
            'date': adate_str,
            'time': str(atime) if atime else '-',
            'arrival_time': str(arr_time) if arr_time else '-',
            'is_done': 1 if is_done_bool else 0,
            'bid': bid,
            'cid': cid,
        })

    core_cat_not_attended = core_cat_total - core_cat_attended
    attendance_rate = round((attended_count / total_appts * 100), 1) if total_appts > 0 else 0
    no_show_rate = round((not_attended_count / total_appts * 100), 1) if total_appts > 0 else 0

    categories = []
    for cid, st in sorted(cat_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        c_tot = st['total']
        c_att = st['attended']
        c_not = st['not_attended']
        categories.append({
            'category_id': cid,
            'category_name': cat_dict.get(cid, 'Unassigned' if cid == 0 else f'Category {cid}'),
            'total_appointments': c_tot,
            'attended': c_att,
            'not_attended': c_not,
            'attendance_rate': round(c_att / c_tot * 100, 1) if c_tot > 0 else 0,
            'no_show_rate': round(c_not / c_tot * 100, 1) if c_tot > 0 else 0,
        })

    branches = []
    for bid, st in sorted(br_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        b_tot = st['total']
        b_att = st['attended']
        b_not = st['not_attended']
        branches.append({
            'branch_id': bid,
            'branch_name': branch_dict.get(bid, 'Main Branch' if bid == 0 else f'Branch {bid}'),
            'total_appointments': b_tot,
            'attended': b_att,
            'not_attended': b_not,
            'attendance_rate': round(b_att / b_tot * 100, 1) if b_tot > 0 else 0,
            'no_show_rate': round(b_not / b_tot * 100, 1) if b_tot > 0 else 0,
        })

    # Fill every calendar day in the selected range so daily report is complete
    daily_trend = []
    try:
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_d < start_d:
            start_d, end_d = end_d, start_d
        cur = start_d
        # Cap fill window to avoid huge empty ranges
        max_days = 92
        day_count = 0
        while cur <= end_d and day_count < max_days:
            d = cur.strftime("%Y-%m-%d")
            st = daily_stats.get(d, {'total': 0, 'attended': 0, 'not_attended': 0})
            tot = st['total']
            att = st['attended']
            not_att = st['not_attended']
            daily_trend.append({
                'date': d,
                'total_appointments': tot,
                'attended': att,
                'not_attended': not_att,
                'attendance_rate': round((att / tot * 100), 1) if tot > 0 else 0,
            })
            cur += timedelta(days=1)
            day_count += 1
    except ValueError:
        for d in sorted(daily_stats.keys()):
            st = daily_stats[d]
            tot = st['total']
            att = st['attended']
            daily_trend.append({
                'date': d,
                'total_appointments': tot,
                'attended': att,
                'not_attended': st['not_attended'],
                'attendance_rate': round((att / tot * 100), 1) if tot > 0 else 0,
            })

    # Fetch patient details for visible records (with search support)
    patient_map = {}
    candidate_appts = filtered_appts_for_patient_table
    if search_q:
        search_like = f"%{search_q}%"
        cursor.execute(
            "SELECT id, code, name, mobile_number FROM patients WHERE name LIKE %s OR surname LIKE %s OR code LIKE %s OR mobile_number LIKE %s LIMIT 300",
            [search_like, search_like, search_like, search_like]
        )
        for pr in cursor.fetchall():
            patient_map[pr[0]] = {
                'code': pr[1] or '-',
                'name': (pr[2] or '').strip() or 'Unknown Patient',
                'mobile': pr[3] or '-'
            }
        candidate_appts = [v for v in candidate_appts if v['pid'] in patient_map]
    else:
        top_pids = list(set(v['pid'] for v in candidate_appts[:200] if v['pid']))
        if top_pids:
            format_strings = ','.join(['%s'] * len(top_pids))
            cursor.execute(f"SELECT id, code, name, mobile_number FROM patients WHERE id IN ({format_strings})", top_pids)
            for pr in cursor.fetchall():
                patient_map[pr[0]] = {
                    'code': pr[1] or '-',
                    'name': (pr[2] or '').strip() or 'Unknown Patient',
                    'mobile': pr[3] or '-'
                }

    patients_data = []
    for v in candidate_appts[:200]:
        pinfo = patient_map.get(v['pid'], {'code': '-', 'name': 'Unknown Patient', 'mobile': '-'})
        patients_data.append({
            'appointment_id': v['id'],
            'date': v['date'],
            'time': v['time'],
            'arrival_time': v['arrival_time'],
            'status': 'Attended' if v['is_done'] == 1 else 'Not Attended',
            'is_done': v['is_done'],
            'code': pinfo['code'],
            'patient_name': pinfo['name'],
            'mobile': pinfo['mobile'],
            'category': cat_dict.get(v['cid'], 'Unassigned'),
            'branch': branch_dict.get(v['bid'], 'Main Branch')
        })

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
