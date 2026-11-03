"""
Optimized Collection report builder.

Strategy:
- Few simple SELECTs (date/branch filtered rows only)
- Filters + KPI / stream / monthly / branch math done in Python
- Keeps MySQL connection time short under Vercel concurrency
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from django.db import connection


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _ym(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m")
    s = str(value)
    return s[:7] if len(s) >= 7 else None


def _ymd_hm(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _ymd(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _payment_label(code: Any, kind: str = "deposit") -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "Other"
    if kind == "deposit":
        return {2: "Cash", 4: "UPI", 3: "Cheque", 5: "NEFT/RTGS", 1: "NetBanking"}.get(c, "Other")
    return {2: "Cash", 4: "UPI", 3: "Cheque", 5: "NEFT/RTGS", 1: "Card/Swipe"}.get(c, "Other")


def _in_range(dt_val: Any, start_date: str, end_date: str) -> bool:
    if not dt_val:
        return False
    if hasattr(dt_val, "strftime"):
        d = dt_val.strftime("%Y-%m-%d")
    else:
        d = str(dt_val)[:10]
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


def build_collection_report(
    *,
    start_date: str,
    end_date: str,
    branch_id: str,
    source_filter: str,
    exclude_gst: bool,
    exclude_cash: bool,
    payment_type: str,
) -> Dict[str, Any]:
    cursor = connection.cursor()

    start_dt = f"{start_date} 00:00:00" if start_date else None
    end_dt = f"{end_date} 23:59:59" if end_date else None

    # -------- 1) indoor_deposits (one fetch) --------
    dep_where = ["1=1"]
    dep_params: List[Any] = []
    if start_dt:
        dep_where.append("d.created_at >= %s")
        dep_params.append(start_dt)
    if end_dt:
        dep_where.append("d.created_at <= %s")
        dep_params.append(end_dt)
    if branch_id:
        dep_where.append("d.branch_id = %s")
        dep_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT
            d.id, d.created_at, d.case_type, d.amount, d.payment_type, d.charge_type,
            d.branch_id, d.is_deleted, d.is_medicare, d.is_pediatric,
            d.patient_id, d.comment, d.remark, d.injection
        FROM indoor_deposits d
        WHERE {" AND ".join(dep_where)}
        """,
        dep_params,
    )
    deposits = cursor.fetchall()

    # -------- 2) appointment_charges (one fetch) --------
    ac_where = ["1=1"]
    ac_params: List[Any] = []
    if start_date:
        ac_where.append("a.date >= %s")
        ac_params.append(start_date)
    if end_date:
        ac_where.append("a.date <= %s")
        ac_params.append(end_date)
    if branch_id:
        ac_where.append("a.branch_id = %s")
        ac_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT
            ac.id, a.date, ac.total, ac.usg, ac.payment_mode, a.branch_id, a.category_id,
            a.patients_id, ac.invoice_no, ac.detail
        FROM appointment_charges ac
        JOIN appointments a ON ac.appointment_id = a.id
        WHERE {" AND ".join(ac_where)}
        """,
        ac_params,
    )
    appt_charges = cursor.fetchall()

    # -------- 3) embryology_invoice (bounded fetch; final date filter in Python) --------
    ei_where = [
        "(ei.payment_cash + ei.payment_upi + ei.payment_cheque + ei.payment_neft + ei.payment_card_swipe) > 0"
    ]
    ei_params: List[Any] = []
    # Coarse DB bound on created_at (wide window); exact voucher-date filter is app-side
    if start_date:
        ei_where.append("ei.created_at >= %s")
        ei_params.append(f"{start_date} 00:00:00")
    if end_date:
        ei_where.append("ei.created_at <= %s")
        ei_params.append(f"{end_date} 23:59:59")
    if branch_id:
        ei_where.append("ei.branch_id = %s")
        ei_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT ei.id, ei.created_at, ei.branch_id, ei.patients_id, ei.process_name,
               ei.payment_cash, ei.payment_upi, ei.payment_cheque, ei.payment_neft, ei.payment_card_swipe
        FROM embryology_invoice ei
        WHERE {" AND ".join(ei_where)}
        """,
        ei_params,
    )
    ei_rows_all = cursor.fetchall()
    ei_ids = [r[0] for r in ei_rows_all]
    voucher_dates: Dict[Any, Any] = {}
    if ei_ids:
        # Resolve dates in one query instead of correlated subquery per row
        format_strings = ",".join(["%s"] * len(ei_ids))
        cursor.execute(
            f"""
            SELECT entry_id, branch_id, date, id
            FROM invoice_vouchers
            WHERE finance_procedure = 'embryology_invoice'
              AND ivf_status = 0
              AND entry_id IN ({format_strings})
            ORDER BY id DESC
            """,
            ei_ids,
        )
        for entry_id, b_id, vdate, _vid in cursor.fetchall():
            key = (entry_id, _i(b_id))
            if key not in voucher_dates:
                voucher_dates[key] = vdate

    embryology_rows = []
    for r in ei_rows_all:
        eid, created_at, b_id, pid, process_name, cash, upi, cheque, neft, card = r
        vdate = voucher_dates.get((_i(eid), _i(b_id)))
        tr_date = vdate or created_at
        if not _in_range(tr_date, start_date, end_date):
            continue
        paid_total = _f(cash) + _f(upi) + _f(cheque) + _f(neft) + _f(card)
        if paid_total <= 0:
            continue
        if exclude_cash and (_f(upi) + _f(cheque) + _f(neft) + _f(card)) <= 0:
            continue
        embryology_rows.append(
            {
                "id": eid,
                "date": tr_date,
                "branch_id": _i(b_id),
                "patient_id": pid,
                "process_name": process_name,
                "cash": _f(cash),
                "upi": _f(upi),
                "cheque": _f(cheque),
                "neft": _f(neft),
                "card": _f(card),
                "gross": (_f(upi) + _f(cheque) + _f(neft) + _f(card)) if exclude_cash else paid_total,
            }
        )

    # -------- 4) income_manager + category (one fetch) --------
    im_where = ["ec.type = 1", "ec.status = 1", "im.amount > 0"]
    im_params: List[Any] = []
    if start_dt:
        im_where.append("im.date >= %s")
        im_params.append(start_date)
    if end_dt:
        im_where.append("im.date <= %s")
        im_params.append(end_date)
    if branch_id:
        im_where.append("(im.branch_id = %s OR im.branch_id = %s)")
        im_params.extend([branch_id, str(branch_id)])

    cursor.execute(
        f"""
        SELECT
            im.id, im.date, im.amount, im.payment_method, im.branch_id,
            ec.is_medicare, ec.is_pediatric
        FROM income_manager im
        JOIN expance_category ec ON ec.id = im.income_category
        WHERE {" AND ".join(im_where)}
        """,
        im_params,
    )
    income_rows = cursor.fetchall()

    # -------- 5) indoor final invoices (one fetch) --------
    inv_where = ["ib.is_final_invoice = 1", "ib.final_invoice_date IS NOT NULL"]
    inv_params: List[Any] = []
    if start_dt:
        inv_where.append("ib.final_invoice_date >= %s")
        inv_params.append(start_dt)
    if end_dt:
        inv_where.append("ib.final_invoice_date <= %s")
        inv_params.append(end_dt)
    if branch_id:
        inv_where.append("ib.branch_id = %s")
        inv_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT
            ib.id, ib.final_invoice_date, ib.branch_id,
            ib.is_medicare_patient, ib.is_pediatric_patient,
            ii.id, ii.grand_total_amt, ii.payment_mode
        FROM indoor_books ib
        LEFT JOIN indoor_invoices ii ON ii.booking_id = ib.id
        WHERE {" AND ".join(inv_where)}
        """,
        inv_params,
    )
    invoice_rows = cursor.fetchall()

    # -------- 6) pharmacy sales + returns (row fetch, GST/cash math in Python) --------
    ph_where = ["mpi.is_deleted = 0", "mpi.department_id = 1"]
    ph_params: List[Any] = []
    if start_date:
        ph_where.append("mpi.date_of_transaction >= %s")
        ph_params.append(start_date)
    if end_date:
        ph_where.append("mpi.date_of_transaction <= %s")
        ph_params.append(end_date)
    if branch_id:
        ph_where.append("mpi.branch_id = %s")
        ph_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT
            mpi.id, mpi.date_of_transaction, mpi.branch_id,
            mpi.sell_price, mpi.sell_price_without_gst,
            mpi.payment_cash, mpi.payment_upi, mpi.payment_cheque, mpi.payment_neft
        FROM medication_patients_invoices mpi
        WHERE {" AND ".join(ph_where)}
        """,
        ph_params,
    )
    ph_rows = cursor.fetchall()

    pr_where = ["msc.department_id = 1"]
    pr_params: List[Any] = []
    if start_date:
        pr_where.append("msc.date_of_transaction >= %s")
        pr_params.append(start_date)
    if end_date:
        pr_where.append("msc.date_of_transaction <= %s")
        pr_params.append(end_date)
    if branch_id:
        pr_where.append("msc.branch_id = %s")
        pr_params.append(branch_id)

    cursor.execute(
        f"""
        SELECT
            msc.id, msc.date_of_transaction, msc.branch_id, msc.patients_id,
            msc.payable_amount, msc.price_without_gst, msc.credit_note_no,
            msc.payment_cash, msc.payment_upi, msc.payment_cheque, msc.payment_neft
        FROM medication_sales_credit msc
        WHERE {" AND ".join(pr_where)}
        """,
        pr_params,
    )
    pr_rows = cursor.fetchall()

    # -------- 7) medicine_given_history --------
    med_where = []
    med_params: List[Any] = []
    if start_date:
        med_where.append("given_date >= %s")
        med_params.append(start_date)
    if end_date:
        med_where.append("given_date <= %s")
        med_params.append(end_date)
    if branch_id:
        med_where.append("branch_id = %s")
        med_params.append(branch_id)
    med_sql = f"WHERE {' AND '.join(med_where)}" if med_where else ""
    cursor.execute(
        f"""
        SELECT id, given_date, branch_id, total_amount
        FROM medicine_given_history
        {med_sql}
        """,
        med_params,
    )
    medicine_rows = cursor.fetchall()

    # -------- 8) branches once --------
    cursor.execute(
        """
        SELECT id, name FROM branch
        WHERE status = 1 OR id IN (SELECT DISTINCT branch_id FROM indoor_deposits)
        ORDER BY name
        """
    )
    branch_rows = cursor.fetchall()
    branches = [{"id": b[0], "name": b[1]} for b in branch_rows]
    branch_name_map = {b["id"]: b["name"] for b in branches}

    # ===================== PYTHON AGGREGATION =====================
    opd_cats = {1, 2, 3, 4, 5, 6, 17, 18, 22}

    def pass_payment(code: Any, mode_field: str = "deposit") -> bool:
        if payment_type:
            try:
                return int(code) == int(payment_type)
            except (TypeError, ValueError):
                return False
        if exclude_cash:
            try:
                # deposit/appt: cash=2 ; income_manager cash=1
                if mode_field == "income":
                    return int(code) not in (1, 2)
                return int(code) != 2
            except (TypeError, ValueError):
                return True
        return True

    # --- deposits ---
    hc_gross = hc_return = 0.0
    hc_credit_count = hc_return_count = 0
    hc_cash = hc_upi = hc_cheque = hc_neft = hc_other = 0.0
    stream_hinj = stream_iui = stream_ivf = 0.0
    stream_hinj_cnt = stream_iui_cnt = stream_ivf_cnt = 0
    ipd_dep_total = ped_dep_total = medicare_dep_total = 0.0
    ipd_dep_cnt = ped_dep_cnt = medicare_dep_cnt = 0
    ped_cash = ped_upi = ped_cheque = ped_neft = 0.0
    medicare_cash = medicare_upi = medicare_cheque = medicare_neft = 0.0
    b_dep = defaultdict(lambda: [0.0] * 7)  # hinj,iui,ivf,ipd_dep,ped_dep,med_dep,return
    hc_monthly = defaultdict(lambda: {"gross_hc": 0.0, "return_hc": 0.0})
    deposit_records = []

    for r in deposits:
        (
            did, created_at, case_type, amount, payment_type_v, charge_type,
            b_id, is_deleted, is_medicare, is_pediatric,
            patient_id, comment, remark, injection,
        ) = r
        amt = _f(amount)
        bid = _i(b_id)
        case = str(case_type or "").strip()
        ct = _i(charge_type)
        ym = _ym(created_at)

        # Core healthcare KPI uses Credit/Debit (legacy parity); streams use is_deleted=0
        if case in ("Credit", "Debit") and pass_payment(payment_type_v):
            if case == "Credit":
                hc_gross += amt
                hc_credit_count += 1
                pt = _i(payment_type_v)
                if pt == 2:
                    hc_cash += amt
                elif pt == 4:
                    hc_upi += amt
                elif pt == 3:
                    hc_cheque += amt
                elif pt == 5:
                    hc_neft += amt
                else:
                    hc_other += amt
                if ym:
                    hc_monthly[ym]["gross_hc"] += amt
            else:
                hc_return += amt
                hc_return_count += 1
                b_dep[bid][6] += amt
                if ym:
                    hc_monthly[ym]["return_hc"] += amt

        deleted = _i(is_deleted)
        if deleted == 0 and case == "Credit" and pass_payment(payment_type_v):
            if ct == 1:
                stream_hinj += amt
                stream_hinj_cnt += 1
                b_dep[bid][0] += amt
            elif ct == 3:
                stream_iui += amt
                stream_iui_cnt += 1
                b_dep[bid][1] += amt
            elif ct == 2:
                stream_ivf += amt
                stream_ivf_cnt += 1
                b_dep[bid][2] += amt
            elif ct == 4:
                is_med = _i(is_medicare) == 1
                is_ped = _i(is_pediatric) == 1
                pt = _i(payment_type_v)
                if is_ped:
                    ped_dep_total += amt
                    ped_dep_cnt += 1
                    b_dep[bid][4] += amt
                    if pt == 2:
                        ped_cash += amt
                    elif pt == 4:
                        ped_upi += amt
                    elif pt == 3:
                        ped_cheque += amt
                    elif pt == 5:
                        ped_neft += amt
                elif is_med:
                    medicare_dep_total += amt
                    medicare_dep_cnt += 1
                    b_dep[bid][5] += amt
                    if pt == 2:
                        medicare_cash += amt
                    elif pt == 4:
                        medicare_upi += amt
                    elif pt == 3:
                        medicare_cheque += amt
                    elif pt == 5:
                        medicare_neft += amt
                else:
                    ipd_dep_total += amt
                    ipd_dep_cnt += 1
                    b_dep[bid][3] += amt

        if case in ("Credit", "Debit") and pass_payment(payment_type_v):
            deposit_records.append(
                {
                    "id": f"HC-{did}",
                    "date": _ymd_hm(created_at),
                    "source": "Healthcare Return" if case.lower() == "debit" else "Healthcare (Deposit)",
                    "source_type": "healthcare",
                    "is_return": case.lower() == "debit",
                    "amount": amt,
                    "patient_id": patient_id,
                    "patient_code": "-",
                    "patient_name": "Walk-in Patient",
                    "branch_name": branch_name_map.get(bid, f"Branch {bid}"),
                    "payment_mode": _payment_label(payment_type_v),
                    "reference": comment or remark or injection or "-",
                    "_pid": patient_id,
                }
            )

    # --- appointment charges ---
    ac_gross = 0.0
    ac_count = 0
    ac_cash = ac_upi = ac_cheque = ac_neft = ac_other = 0.0
    stream_usg = stream_opd = 0.0
    stream_usg_cnt = stream_opd_cnt = 0
    b_appt = defaultdict(lambda: [0.0, 0.0])  # usg, opd
    ac_records = []

    for r in appt_charges:
        (
            acid, adate, total, usg, payment_mode, b_id, category_id,
            patients_id, invoice_no, detail,
        ) = r
        if not pass_payment(payment_mode):
            continue
        tot = _f(total)
        usg_amt = _f(usg)
        bid = _i(b_id)
        cid = _i(category_id)
        ym = _ym(adate)

        # Component B excludes category 7 and requires total > 0
        if cid != 7 and tot > 0:
            ac_gross += tot
            ac_count += 1
            pm = _i(payment_mode)
            if pm == 2:
                ac_cash += tot
            elif pm == 4:
                ac_upi += tot
            elif pm == 3:
                ac_cheque += tot
            elif pm == 5:
                ac_neft += tot
            else:
                ac_other += tot
            if ym:
                hc_monthly[ym]["gross_hc"] += tot

            ac_records.append(
                {
                    "id": f"OPD-{acid}",
                    "date": _ymd(adate),
                    "source": "OPD / Consultation",
                    "source_type": "healthcare",
                    "is_return": False,
                    "amount": tot,
                    "patient_id": patients_id,
                    "patient_code": "-",
                    "patient_name": "OPD Patient",
                    "branch_name": branch_name_map.get(bid, f"Branch {bid}"),
                    "payment_mode": _payment_label(payment_mode, "appt"),
                    "reference": invoice_no or detail or "OPD Charge",
                    "_pid": patients_id,
                }
            )

        if usg_amt > 0:
            stream_usg += usg_amt
            stream_usg_cnt += 1
            b_appt[bid][0] += usg_amt

        if cid in opd_cats:
            opd_amt = tot - usg_amt
            stream_opd += opd_amt
            stream_opd_cnt += 1
            b_appt[bid][1] += opd_amt

    # --- embryology ---
    ei_gross = ei_cash = ei_upi = ei_cheque = ei_neft = ei_other = 0.0
    ei_count = 0
    b_emb = defaultdict(float)
    ei_records = []
    for row in embryology_rows:
        ei_gross += row["gross"]
        ei_count += 1
        if not exclude_cash:
            ei_cash += row["cash"]
        ei_upi += row["upi"]
        ei_cheque += row["cheque"]
        ei_neft += row["neft"]
        ei_other += row["card"]
        b_emb[row["branch_id"]] += row["gross"]
        ym = _ym(row["date"])
        if ym:
            hc_monthly[ym]["gross_hc"] += row["gross"]
        mode = "Cash"
        if row["upi"] > 0:
            mode = "UPI"
        elif row["cash"] > 0 and not exclude_cash:
            mode = "Cash"
        elif row["cheque"] > 0:
            mode = "Cheque"
        elif row["neft"] > 0:
            mode = "NEFT/RTGS"
        elif row["card"] > 0:
            mode = "Card/Swipe"
        ei_records.append(
            {
                "id": f"EMB-{row['id']}",
                "date": _ymd_hm(row["date"]),
                "source": "Embryology / Andrology",
                "source_type": "healthcare",
                "is_return": False,
                "amount": row["gross"],
                "patient_id": row["patient_id"],
                "patient_code": "-",
                "patient_name": "Lab Patient",
                "branch_name": branch_name_map.get(row["branch_id"], f"Branch {row['branch_id']}"),
                "payment_mode": mode,
                "reference": row["process_name"] or "Embryology Invoice",
                "_pid": row["patient_id"],
            }
        )
    stream_emb = round(ei_gross, 2)
    stream_emb_cnt = ei_count

    # --- income manager ---
    im_gross = im_cash = im_upi = im_cheque = im_neft = im_other = 0.0
    im_count = 0
    stream_oinc = ped_opd_total = medicare_opd_total = 0.0
    stream_oinc_cnt = ped_opd_cnt = medicare_opd_cnt = 0
    b_im = defaultdict(lambda: [0.0, 0.0, 0.0])  # oinc, ped, medicare

    for r in income_rows:
        imid, imdate, amount, payment_method, b_id, is_medicare, is_pediatric = r
        if exclude_cash and _i(payment_method) in (1, 2):
            # stream O.Income uses != 1 when exclude_cash; keep close parity
            if _i(payment_method) == 1:
                continue
        amt = _f(amount)
        bid = _i(b_id)
        is_med = _i(is_medicare) == 1
        is_ped = _i(is_pediatric) == 1
        pm = _i(payment_method)

        # Component D aggregate (all type=1 status=1)
        im_gross += amt
        im_count += 1
        if not exclude_cash and pm in (1, 2):
            im_cash += amt
        elif pm == 4:
            im_upi += amt
        elif pm == 3:
            im_cheque += amt
        elif pm == 5:
            im_neft += amt
        elif pm not in (1, 2, 3, 4, 5):
            im_other += amt

        if is_ped:
            ped_opd_total += amt
            ped_opd_cnt += 1
            b_im[bid][1] += amt
            if pm == 1:
                ped_cash += amt
            elif pm == 3:
                ped_upi += amt
            elif pm == 2:
                ped_cheque += amt
            elif pm == 4:
                ped_neft += amt
        elif is_med:
            medicare_opd_total += amt
            medicare_opd_cnt += 1
            b_im[bid][2] += amt
            if pm == 1:
                medicare_cash += amt
            elif pm == 3:
                medicare_upi += amt
            elif pm == 2:
                medicare_cheque += amt
            elif pm == 4:
                medicare_neft += amt
        else:
            stream_oinc += amt
            stream_oinc_cnt += 1
            b_im[bid][0] += amt

    # --- indoor invoices ---
    ipd_inv_total = ped_inv_total = medicare_inv_total = 0.0
    ipd_inv_cnt = ped_inv_cnt = medicare_inv_cnt = 0
    b_inv = defaultdict(lambda: [0.0, 0.0, 0.0])

    for r in invoice_rows:
        (
            ibid, final_invoice_date, b_id, is_medicare_patient, is_pediatric_patient,
            ii_id, grand_total_amt, payment_mode,
        ) = r
        if ii_id is None:
            continue
        if not pass_payment(payment_mode):
            continue
        amt = _f(grand_total_amt)
        bid = _i(b_id)
        is_med = _i(is_medicare_patient) == 1
        is_ped = _i(is_pediatric_patient) == 1
        pm = _i(payment_mode)
        if is_ped:
            ped_inv_total += amt
            ped_inv_cnt += 1
            b_inv[bid][1] += amt
            if pm == 2:
                ped_cash += amt
            elif pm == 4:
                ped_upi += amt
            elif pm == 3:
                ped_cheque += amt
            elif pm == 5:
                ped_neft += amt
        elif is_med:
            medicare_inv_total += amt
            medicare_inv_cnt += 1
            b_inv[bid][2] += amt
            if pm == 2:
                medicare_cash += amt
            elif pm == 4:
                medicare_upi += amt
            elif pm == 3:
                medicare_cheque += amt
            elif pm == 5:
                medicare_neft += amt
        else:
            ipd_inv_total += amt
            ipd_inv_cnt += 1
            b_inv[bid][0] += amt

    stream_ipd = round(ipd_inv_total + ipd_dep_total, 2)
    stream_ipd_cnt = ipd_inv_cnt + ipd_dep_cnt
    stream_pediatric = round(ped_opd_total + ped_inv_total + ped_dep_total, 2)
    stream_ped_cnt = ped_opd_cnt + ped_inv_cnt + ped_dep_cnt
    stream_medicare = round(medicare_opd_total + medicare_inv_total + medicare_dep_total, 2)
    stream_med_cnt = medicare_opd_cnt + medicare_inv_cnt + medicare_dep_cnt

    # --- medicine history ---
    stream_medicine = 0.0
    stream_medicine_cnt = 0
    b_med = defaultdict(float)
    for mid, given_date, b_id, total_amount in medicine_rows:
        if not _in_range(given_date, start_date, end_date):
            continue
        amt = _f(total_amount)
        stream_medicine += amt
        stream_medicine_cnt += 1
        b_med[_i(b_id)] += amt

    # --- pharmacy ---
    ph_gross = ph_cash = ph_upi = ph_cheque = ph_neft = 0.0
    ph_count = 0
    ph_monthly = defaultdict(float)
    b_ph = defaultdict(float)

    for r in ph_rows:
        (
            pid, tr_date, b_id, sell_price, sell_wo_gst,
            cash, upi, cheque, neft,
        ) = r
        sell = _f(sell_price)
        sell_wo = _f(sell_wo_gst)
        ratio = (sell_wo / sell) if sell else 0.0
        cash_v, upi_v, cheque_v, neft_v = _f(cash), _f(upi), _f(cheque), _f(neft)
        if exclude_gst:
            metric = (upi_v + cheque_v + neft_v) * ratio if exclude_cash else sell_wo
            c_m = 0.0 if exclude_cash else cash_v * ratio
            u_m = upi_v * ratio
            ch_m = cheque_v * ratio
            n_m = neft_v * ratio
        else:
            metric = (upi_v + cheque_v + neft_v) if exclude_cash else sell
            c_m = 0.0 if exclude_cash else cash_v
            u_m, ch_m, n_m = upi_v, cheque_v, neft_v
        ph_gross += metric
        ph_count += 1
        ph_cash += c_m
        ph_upi += u_m
        ph_cheque += ch_m
        ph_neft += n_m
        ym = _ym(tr_date)
        if ym:
            ph_monthly[ym] += metric
        b_ph[_i(b_id)] += metric

    pr_return = pr_cash = pr_upi = pr_cheque = pr_neft = 0.0
    pr_count = 0
    pr_monthly = defaultdict(float)
    b_pr = defaultdict(float)
    pr_records = []

    for r in pr_rows:
        (
            rid, tr_date, b_id, patients_id, payable, price_wo, credit_note,
            cash, upi, cheque, neft,
        ) = r
        payable_v = _f(payable)
        price_wo_v = _f(price_wo)
        ratio = (price_wo_v / payable_v) if payable_v else 0.0
        cash_v, upi_v, cheque_v, neft_v = _f(cash), _f(upi), _f(cheque), _f(neft)
        if exclude_gst:
            metric = (upi_v + cheque_v + neft_v) * ratio if exclude_cash else price_wo_v
            c_m = 0.0 if exclude_cash else cash_v * ratio
            u_m = upi_v * ratio
            ch_m = cheque_v * ratio
            n_m = neft_v * ratio
        else:
            metric = (upi_v + cheque_v + neft_v) if exclude_cash else payable_v
            c_m = 0.0 if exclude_cash else cash_v
            u_m, ch_m, n_m = upi_v, cheque_v, neft_v
        pr_return += metric
        pr_count += 1
        pr_cash += c_m
        pr_upi += u_m
        pr_cheque += ch_m
        pr_neft += n_m
        ym = _ym(tr_date)
        if ym:
            pr_monthly[ym] += metric
        bid = _i(b_id)
        b_pr[bid] += metric
        mode = "Cash"
        if upi_v > 0:
            mode = "UPI"
        elif cash_v > 0:
            mode = "Cash"
        elif cheque_v > 0:
            mode = "Cheque"
        elif neft_v > 0:
            mode = "NEFT"
        pr_records.append(
            {
                "id": f"PH-RET-{rid}",
                "date": _ymd(tr_date),
                "source": "Pharmacy Return (Credit Note)",
                "source_type": "pharmacy_return",
                "is_return": True,
                "amount": cash_v + upi_v + cheque_v + neft_v,
                "patient_id": patients_id,
                "patient_code": "-",
                "patient_name": "Pharmacy Customer",
                "branch_name": branch_name_map.get(bid, f"Branch {bid}"),
                "payment_mode": mode,
                "reference": f"Credit Note #{credit_note or rid}",
                "_pid": patients_id,
            }
        )

    total_income_amount = round(
        stream_usg + stream_hinj + stream_iui + stream_ivf + stream_opd
        + stream_ipd + stream_oinc + stream_medicine + stream_emb
        + stream_pediatric + stream_medicare,
        2,
    )
    total_healthcare_collection = total_income_amount
    total_pharmacy_collection = round(ph_gross, 2)
    total_payment_return = round(hc_return + pr_return, 2)
    total_gross_collection = round(total_healthcare_collection + total_pharmacy_collection, 2)
    net_collection = round(total_gross_collection - total_payment_return, 2)

    combined_hc_cash = round(hc_cash + ac_cash + ei_cash + im_cash + ped_cash + medicare_cash, 2)
    combined_hc_upi = round(hc_upi + ac_upi + ei_upi + im_upi + ped_upi + medicare_upi, 2)
    combined_hc_cheque = round(hc_cheque + ac_cheque + ei_cheque + im_cheque + ped_cheque + medicare_cheque, 2)
    combined_hc_neft = round(hc_neft + ac_neft + ei_neft + im_neft + ped_neft + medicare_neft, 2)
    combined_hc_other = round(hc_other + ac_other + ei_other + im_other, 2)

    total_cash_net = 0.0 if exclude_cash else round(max(0.0, (combined_hc_cash + ph_cash) - pr_cash), 2)
    total_upi_net = round(max(0.0, (combined_hc_upi + ph_upi) - pr_upi), 2)
    total_cheque_net = round(max(0.0, (combined_hc_cheque + ph_cheque) - pr_cheque), 2)
    total_neft_net = round(max(0.0, (combined_hc_neft + ph_neft) - pr_neft), 2)
    total_other_net = round(combined_hc_other, 2)

    # monthly trend
    all_months = sorted(set(list(hc_monthly.keys()) + list(ph_monthly.keys()) + list(pr_monthly.keys())))
    monthly_trend = []
    for ym in all_months:
        ghc = hc_monthly.get(ym, {}).get("gross_hc", 0.0)
        rhc = hc_monthly.get(ym, {}).get("return_hc", 0.0)
        gph = ph_monthly.get(ym, 0.0)
        rph = pr_monthly.get(ym, 0.0)
        tot_gross = ghc + gph
        tot_ret = rhc + rph
        monthly_trend.append(
            {
                "month": ym,
                "net_collection": round(tot_gross - tot_ret, 2),
                "total_collection": round(tot_gross, 2),
                "healthcare_collection": round(ghc, 2),
                "pharmacy_collection": round(gph - rph, 2),
                "payment_return": round(tot_ret, 2),
            }
        )

    # branch breakdown
    active_bids = set(
        list(b_appt.keys())
        + list(b_dep.keys())
        + list(b_inv.keys())
        + list(b_im.keys())
        + list(b_med.keys())
        + list(b_emb.keys())
        + list(b_ph.keys())
        + list(b_pr.keys())
    )
    if branch_id:
        try:
            active_bids = {int(branch_id)}
        except ValueError:
            pass

    branch_breakdown = []
    for bid in active_bids:
        b_usg, b_opd = b_appt.get(bid, [0.0, 0.0])
        dep_vals = b_dep.get(bid, [0.0] * 7)
        b_hinj, b_iui, b_ivf, b_ipd_dep, b_ped_dep, b_med_dep, b_rhc = dep_vals
        b_ipd_inv, b_ped_inv, b_med_inv = b_inv.get(bid, [0.0, 0.0, 0.0])
        b_oinc, b_ped_opd, b_med_opd = b_im.get(bid, [0.0, 0.0, 0.0])
        b_med_amt = b_med.get(bid, 0.0)
        b_emb_amt = b_emb.get(bid, 0.0)
        b_ghc = round(
            b_usg + b_hinj + b_iui + b_ivf + b_opd
            + (b_ipd_inv + b_ipd_dep) + b_oinc + b_med_amt + b_emb_amt
            + (b_ped_opd + b_ped_inv + b_ped_dep)
            + (b_med_opd + b_med_inv + b_med_dep),
            2,
        )
        b_gph = round(b_ph.get(bid, 0.0), 2)
        b_rph = round(b_pr.get(bid, 0.0), 2)
        b_gross = round(b_ghc + b_gph, 2)
        b_ret = round(b_rhc + b_rph, 2)
        b_net = round(b_gross - b_ret, 2)
        if b_gross > 0 or b_ret > 0:
            branch_breakdown.append(
                {
                    "branch_id": bid,
                    "branch_name": branch_name_map.get(bid, f"Branch {bid}"),
                    "net_collection": b_net,
                    "total_collection": b_gross,
                    "healthcare_collection": b_ghc,
                    "pharmacy_collection": b_gph,
                    "payment_return": b_ret,
                    "healthcare_return": round(b_rhc, 2),
                    "pharmacy_return": round(b_rph, 2),
                    "pct_of_total": round((b_net / net_collection * 100), 1) if net_collection > 0 else 0,
                }
            )
    branch_breakdown.sort(key=lambda x: x["total_collection"], reverse=True)

    # Enrich top ledger patient names in one query
    records = deposit_records[:60] + ac_records[:50] + ei_records[:40] + pr_records[:60]
    pids = list({r.get("_pid") for r in records if r.get("_pid")})
    patient_map: Dict[Any, Tuple[str, str]] = {}
    if pids:
        format_strings = ",".join(["%s"] * len(pids))
        cursor.execute(
            f"SELECT id, code, name FROM patients WHERE id IN ({format_strings})",
            pids,
        )
        for pid, code, name in cursor.fetchall():
            patient_map[pid] = (code or "-", (name or "").strip() or "Walk-in Patient")

    for rec in records:
        pid = rec.pop("_pid", None)
        if pid in patient_map:
            rec["patient_code"], rec["patient_name"] = patient_map[pid]
    records.sort(key=lambda x: x["date"], reverse=True)

    categories_breakdown = [
        {"key": "USG", "name": "USG", "amount": round(stream_usg, 2), "count": stream_usg_cnt, "icon": "📡", "color": "#0284C7", "unit": "Scans"},
        {"key": "H_INJ", "name": "H.Inj", "amount": round(stream_hinj, 2), "count": stream_hinj_cnt, "icon": "💉", "color": "#10B981", "unit": "Injections"},
        {"key": "IUI", "name": "IUI", "amount": round(stream_iui, 2), "count": stream_iui_cnt, "icon": "🔬", "color": "#F59E0B", "unit": "Cycles"},
        {"key": "IVF", "name": "IVF", "amount": round(stream_ivf, 2), "count": stream_ivf_cnt, "icon": "🧬", "color": "#8B5CF6", "unit": "Treatments"},
        {"key": "OPD", "name": "OPD", "amount": round(stream_opd, 2), "count": stream_opd_cnt, "icon": "🩺", "color": "#06B6D4", "unit": "Patients"},
        {"key": "IPD", "name": "IPD", "amount": stream_ipd, "count": stream_ipd_cnt, "icon": "🛏️", "color": "#EC4899", "unit": "Indoor"},
        {"key": "O_INCOME", "name": "O.Income", "amount": round(stream_oinc, 2), "count": stream_oinc_cnt, "icon": "📈", "color": "#F97316", "unit": "Entries"},
        {"key": "MEDICINE", "name": "Medicine Income", "amount": round(stream_medicine, 2), "count": stream_medicine_cnt, "icon": "💊", "color": "#14B8A6", "unit": "Invoices"},
        {"key": "EMBRYOLOGY", "name": "Embryology Income", "amount": stream_emb, "count": stream_emb_cnt, "icon": "🧪", "color": "#6366F1", "unit": "Procedures"},
        {"key": "PEDIATRIC", "name": "Pediatric Total Income", "amount": stream_pediatric, "count": stream_ped_cnt, "icon": "👶", "color": "#F43F5E", "unit": "Cases"},
        {"key": "MEDICARE", "name": "Medicare Total Income", "amount": stream_medicare, "count": stream_med_cnt, "icon": "🛡️", "color": "#3B82F6", "unit": "Cases"},
        {
            "key": "TOTAL_INCOME",
            "name": "Total Income",
            "amount": total_income_amount,
            "count": stream_usg_cnt + stream_hinj_cnt + stream_iui_cnt + stream_ivf_cnt + stream_opd_cnt + stream_ipd_cnt + stream_oinc_cnt + stream_medicine_cnt + stream_emb_cnt + stream_ped_cnt + stream_med_cnt,
            "icon": "💎",
            "color": "#0F172A",
            "unit": "Total Inflow",
        },
    ]

    return {
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
                "total_transactions": hc_credit_count + hc_return_count + ph_count + pr_count,
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
            },
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
            "exclude_cash": 1 if exclude_cash else 0,
        },
    }
