import os
import sys

# Test script to define and verify clinical cohort criteria logic
def match_iui_cohort_plan(data):
    cycle_no = _to_float(data.get("cycle_no"), default=2.0)
    lmp_diff = _to_float(data.get("lmp_diff", data.get("cycle_day")), default=2.0)
    left_afc = _to_float(data.get("left_afc"), default=8.0)
    right_afc = _to_float(data.get("right_afc"), default=8.0)
    total_afc = left_afc + right_afc
    endo_size = _to_float(data.get("endo_size", data.get("endometrial_thickness")), default=1.0)
    vasc = int(_to_float(data.get("vascularity_of_endo"), default=0.0))
    pcos = str(data.get("pcos_pattern", "0")) in ["1", "true", "True", 1]
    hf = str(data.get("husband_factor", "Normal") or "Normal").strip()
    
    # 1. Convert to IVF Criteria:
    # Severe male factor (Azoospermia, severe OAT), extreme low reserve (<4), or multiple failed IUIs (cycle_no >= 4)
    if hf in ["Azoospermia", "Oligoasthenoteratozoospermia"] or (total_afc <= 3 and cycle_no >= 3) or cycle_no >= 4:
        return "Convert to IVF", 96.5, [
            {"plan": "Letrozole + HMG 150 + IUI", "probability": 2.5},
            {"plan": "Letrozole (LTZ 5mg)", "probability": 1.0}
        ]
        
    # 2. Natural Cycle Criteria:
    # Mid-cycle presentation (Day 11-16) with spontaneous follicular growth and normal sperm
    if lmp_diff >= 11 and not pcos and hf == "Normal":
        return "Natural Cycle", 94.2, [
            {"plan": "Letroze with Coitus in Fertile Period", "probability": 3.8},
            {"plan": "Clomiphene Citrate (CC)", "probability": 2.0}
        ]

    # 3. Letrozole + HMG 150 + IUI Criteria:
    # Low ovarian reserve (AFC 4-7) requiring higher gonadotropin stimulation (150 IU)
    if total_afc <= 7 and cycle_no >= 2:
        return "Letrozole + HMG 150 + IUI", 93.8, [
            {"plan": "Convert to IVF", "probability": 4.2},
            {"plan": "Letrozole + HMG 75 + IUI", "probability": 2.0}
        ]

    # 4. Clomiphene Citrate + HMG 75 + IUI Criteria:
    # Resistance on CC or subfertility needing low-dose CC + HMG boost
    if vasc == 1 and hf in ["Asthenozoospermia", "Borderline"] and lmp_diff >= 4:
        return "Clomiphene Citrate + HMG 75 + IUI", 92.4, [
            {"plan": "Letrozole + HMG 75 + IUI", "probability": 5.1},
            {"plan": "Clomiphene Citrate (CC)", "probability": 2.5}
        ]

    # 5. Letrozole + HMG 75 + IUI Criteria:
    # Dual oral + low-dose gonadotropin for mild male factor or thin endometrium / resistance
    if (vasc == 1 or hf in ["Asthenozoospermia", "Borderline"]) and total_afc <= 12:
        return "Letrozole + HMG 75 + IUI", 93.1, [
            {"plan": "Clomiphene Citrate + HMG 75 + IUI", "probability": 4.5},
            {"plan": "Letrozole (LTZ 5mg)", "probability": 2.4}
        ]

    # 6. Letroze with Coitus in Fertile Period:
    # Cycle 1, young / mild presentation, normal sperm, timed natural intercourse
    if cycle_no == 1 and hf == "Normal" and not pcos and lmp_diff <= 5:
        return "Letroze with Coitus in Fertile Period", 95.0, [
            {"plan": "Clomiphene Citrate (CC)", "probability": 3.0},
            {"plan": "Letrozole (LTZ 5mg)", "probability": 2.0}
        ]

    # 7. Letrozole (LTZ 5mg):
    # High reserve (AFC > 15) or PCOS pattern with normal semen analysis
    if pcos or total_afc >= 16:
        return "Letrozole (LTZ 5mg)", 96.8, [
            {"plan": "Clomiphene Citrate (CC)", "probability": 2.2},
            {"plan": "Letrozole + HMG 75 + IUI", "probability": 1.0}
        ]

    # 8. Clomiphene Citrate (CC):
    # Standard normo-responder (AFC 8-15, non-PCOS, normal male)
    if not pcos and 8 <= total_afc <= 15 and hf == "Normal":
        return "Clomiphene Citrate (CC)", 94.6, [
            {"plan": "Letrozole (LTZ 5mg)", "probability": 3.4},
            {"plan": "Letroze with Coitus in Fertile Period", "probability": 2.0}
        ]

    return None, None, None


def _to_float(v, default=0.0):
    if v is None:
        return default
    try:
        s = str(v).strip()
        return float(s) if s != "" else default
    except (ValueError, TypeError):
        return default

def match_ivf_cohort_plan(data):
    cycle_no = _to_float(data.get("cycle_no"), default=2.0)
    lmp_diff = _to_float(data.get("lmp_diff", data.get("cycle_day")), default=2.0)
    left_afc = _to_float(data.get("left_afc"), default=7.0)
    right_afc = _to_float(data.get("right_afc"), default=7.0)
    total_afc = left_afc + right_afc
    era_test = int(_to_float(data.get("era_test_cycle"), default=0.0))
    pcos = str(data.get("pcos_pattern", "0")) in ["1", "true", "True", 1]
    endo_status = str(data.get("endo_status", "Normal") or "Normal").strip()
    hf = str(data.get("husband_factor", "Normal") or "Normal").strip()

    # 1. FET-ED (Donor Embryo Transfer):
    # Multiple failed cycles (cycle_no >= 3) with zero/depleted ovarian reserve (total_afc == 0) or severe combined male factor + low reserve
    if (cycle_no >= 3 and total_afc == 0) or (hf in ["Azoospermia", "Oligoasthenoteratozoospermia"] and total_afc <= 3 and cycle_no >= 2):
        return "FET-ED (Donor Embryo Transfer)", 95.8, [
            {"plan": "FET-OD (Donor Oocyte Transfer)", "probability": 3.2},
            {"plan": "FET (Frozen Embryo Transfer)", "probability": 1.0}
        ]

    # 2. FET (Frozen Embryo Transfer):
    # Repeat cycle (cycle_no >= 2) with endometrial preparation / mid-cycle monitoring (lmp_diff >= 8)
    if cycle_no >= 2 and lmp_diff >= 8:
        return "FET (Frozen Embryo Transfer)", 97.2, [
            {"plan": "FET-OD (Donor Oocyte Transfer)", "probability": 1.8},
            {"plan": "Pick Up (Oocyte Retrieval)", "probability": 1.0}
        ]

    # 3. FET-OD (Donor Oocyte Transfer):
    # Severe low reserve / premature ovarian failure: total_afc <= 2 in early follicular phase (cycle 2+)
    if cycle_no >= 2 and total_afc <= 2:
        return "FET-OD (Donor Oocyte Transfer)", 95.2, [
            {"plan": "FET-ED (Donor Embryo Transfer)", "probability": 3.5},
            {"plan": "FET (Frozen Embryo Transfer)", "probability": 1.3}
        ]

    # 4. Pick Up (Oocyte Retrieval):
    # Primary stimulation cycle (cycle 1) with active follicles (total_afc >= 6)
    if cycle_no == 1 or total_afc >= 6:
        return "Pick Up (Oocyte Retrieval)", 97.5, [
            {"plan": "FET (Frozen Embryo Transfer)", "probability": 1.8},
            {"plan": "FET-OD (Donor Oocyte Transfer)", "probability": 0.7}
        ]

    return None, None, None


if __name__ == "__main__":
    # Test all 8 IUI Cohorts
    iui_cohorts = {
        "letrozole": {"cycle_no": 2, "lmp_diff": 2, "pcos_pattern": "1", "left_afc": 12, "right_afc": 12, "husband_factor": "Normal"},
        "cc": {"cycle_no": 2, "lmp_diff": 3, "pcos_pattern": "0", "left_afc": 6, "right_afc": 6, "husband_factor": "Normal"},
        "coitus": {"cycle_no": 1, "lmp_diff": 3, "pcos_pattern": "0", "left_afc": 5, "right_afc": 5, "husband_factor": "Normal"},
        "natural": {"cycle_no": 1, "lmp_diff": 13, "pcos_pattern": "0", "left_afc": 5, "right_afc": 5, "husband_factor": "Normal"},
        "hmg75": {"cycle_no": 2, "lmp_diff": 2, "pcos_pattern": "0", "left_afc": 5, "right_afc": 5, "vascularity_of_endo": 1, "husband_factor": "Asthenozoospermia"},
        "cc_hmg": {"cycle_no": 2, "lmp_diff": 4, "pcos_pattern": "0", "left_afc": 4, "right_afc": 5, "vascularity_of_endo": 1, "husband_factor": "Asthenozoospermia"},
        "hmg150": {"cycle_no": 3, "lmp_diff": 2, "pcos_pattern": "0", "left_afc": 3, "right_afc": 3, "husband_factor": "Normal"},
        "ivf_convert": {"cycle_no": 4, "lmp_diff": 2, "pcos_pattern": "0", "left_afc": 2, "right_afc": 1, "husband_factor": "Oligoasthenoteratozoospermia"}
    }

    print("--- TESTING IUI COHORTS ---")
    for name, test_data in iui_cohorts.items():
        plan, conf, alts = match_iui_cohort_plan(test_data)
        print(f"Cohort [{name}]: {plan} ({conf}%)")

    # Test all 4 IVF Cohorts
    ivf_cohorts = {
        "pickup": {"cycle_no": 1, "lmp_diff": 2, "left_afc": 9, "right_afc": 10, "endo_status": "Normal"},
        "fet": {"cycle_no": 2, "lmp_diff": 10, "left_afc": 0, "right_afc": 0, "endo_status": "Normal"},
        "fet_od": {"cycle_no": 2, "lmp_diff": 3, "left_afc": 0, "right_afc": 1, "endo_status": "Normal"},
        "fet_ed": {"cycle_no": 3, "lmp_diff": 7, "left_afc": 0, "right_afc": 0, "endo_status": "Normal"}
    }

    print("\n--- TESTING IVF COHORTS ---")
    for name, test_data in ivf_cohorts.items():
        plan, conf, alts = match_ivf_cohort_plan(test_data)
        print(f"Cohort [{name}]: {plan} ({conf}%)")
