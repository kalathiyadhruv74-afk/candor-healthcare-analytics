import collections, json, re

# Step 1: Collect patient IDs from ivf and iui
ivf_pids = set()
iui_pids = set()

with open('candor_healthcare (3).sql', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if line.startswith('INSERT INTO ivf '):
            parts = line[len('INSERT INTO ivf VALUES('):].split(',', 3)
            if len(parts) >= 2:
                try:
                    ivf_pids.add(int(parts[1].strip()))
                except:
                    pass
        elif line.startswith('INSERT INTO iui '):
            parts = line[len('INSERT INTO iui VALUES('):].split(',', 3)
            if len(parts) >= 2:
                try:
                    iui_pids.add(int(parts[1].strip()))
                except:
                    pass

# Note: As per the user's explicit rule:
# If a patient converted/transferred from IUI to IVF, count them under IVF!
# Only if they were strictly IUI without IVF, count them under IUI.
pure_iui_pids = iui_pids - ivf_pids

def get_source(pid):
    if pid in ivf_pids:
        return 'IVF'
    elif pid in pure_iui_pids:
        return 'IUI'
    else:
        return 'Direct Maternity'

# Step 2: Track loss categories and classify by treatment source
categories = {
    'Ectopic Pregnancy': {'pids': set(), 'name': 'Ectopic Pregnancy (Tubal/Extrauterine Implantation)'},
    'Missed Abortion': {'pids': set(), 'name': 'Missed Abortion (Silent Embryonic Arrest)'},
    'Major Anomalies': {'pids': set(), 'name': 'Major Congenital & Structural Anomalies'},
    'D&E / D&C Evacuation': {'pids': set(), 'name': 'D&E / D&C Surgical Uterine Evacuation'},
    'Blighted Ovum': {'pids': set(), 'name': 'Blighted Ovum (Anembryonic Sac)'},
    'Cardiac Absence': {'pids': set(), 'name': 'Fetal Cardiac Cessation / Absence'},
    'Spontaneous Miscarriage': {'pids': set(), 'name': 'Spontaneous Miscarriage'},
    'IUD / Stillbirth': {'pids': set(), 'name': 'Intrauterine Fetal Demise (IUD / Stillbirth)'}
}

all_loss_pids = set()
delivery_pids = collections.defaultdict(set)

with open('candor_healthcare (3).sql', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if line.startswith('INSERT INTO anc_history '):
            parts = line[len('INSERT INTO anc_history VALUES('):].split(',', 4)
            if len(parts) >= 3:
                try:
                    pid = int(parts[2].strip())
                    low = line.lower()
                    src = get_source(pid)

                    if any(t in low for t in ['lscs', 'ftnd', 'delivery', 'cesarean', 'live birth', 'baby boy', 'baby girl', 'delivered', '37 wks', '38 wks', '39 wks', '40 wks', '37 weeks', '38 weeks', '39 weeks', '40 weeks', '9 month']):
                        delivery_pids[src].add(pid)

                    is_loss = False
                    if 'ec_topic' in low or 'ectopic' in low:
                        m_ec = re.findall(r'"ec_topic":"(.*?)"', line)
                        if (m_ec and m_ec[0] not in ['null', 'no', 'none', 'false']) or 'ectopic' in low:
                            categories['Ectopic Pregnancy']['pids'].add(pid)
                            is_loss = True
                    if 'missed abortion' in low:
                        categories['Missed Abortion']['pids'].add(pid)
                        is_loss = True
                    if 'anomalous' in low or 'anencephaly' in low or 'anomaly' in low:
                        categories['Major Anomalies']['pids'].add(pid)
                        is_loss = True
                    if 'd&e' in low or 'd&c' in low or 'evacuation' in low:
                        categories['D&E / D&C Evacuation']['pids'].add(pid)
                        is_loss = True
                    if 'blighted ovum' in low or 'anembryonic' in low:
                        categories['Blighted Ovum']['pids'].add(pid)
                        is_loss = True
                    if 'cardiac activity absent' in low or 'no cardiac' in low:
                        categories['Cardiac Absence']['pids'].add(pid)
                        is_loss = True
                    if 'spontaneous abortion' in low or 'miscarriage' in low:
                        categories['Spontaneous Miscarriage']['pids'].add(pid)
                        is_loss = True
                    if 'iud' in low or 'fetal demise' in low or 'intrauterine death' in low or 'stillbirth' in low:
                        categories['IUD / Stillbirth']['pids'].add(pid)
                        is_loss = True

                    if is_loss:
                        all_loss_pids.add(pid)
                except:
                    pass

print("=== TOTAL LOSS PATIENTS BY SOURCE ===")
loss_by_source = collections.Counter([get_source(p) for p in all_loss_pids])
for k, v in loss_by_source.items():
    print(f"  {k}: {v} patients ({v/len(all_loss_pids)*100:.1f}%)")

print("\n=== DETAILED REASONS BY IVF vs IUI vs DIRECT ===")
results = []
for cat_key, data in categories.items():
    pids = data['pids']
    ivf_count = sum(1 for p in pids if get_source(p) == 'IVF')
    iui_count = sum(1 for p in pids if get_source(p) == 'IUI')
    direct_count = sum(1 for p in pids if get_source(p) == 'Direct Maternity')
    total = len(pids)
    results.append({
        'category': cat_key,
        'full_name': data['name'],
        'total': total,
        'ivf': ivf_count,
        'iui': iui_count,
        'direct': direct_count,
        'ivf_pct': round(ivf_count / total * 100, 1) if total else 0,
        'iui_pct': round(iui_count / total * 100, 1) if total else 0,
        'direct_pct': round(direct_count / total * 100, 1) if total else 0
    })
    print(f"{cat_key} (Total: {total}): IVF={ivf_count} ({ivf_count/total*100:.1f}%), IUI={iui_count} ({iui_count/total*100:.1f}%), Direct={direct_count} ({direct_count/total*100:.1f}%)")

with open('data/anc_loss_by_treatment_source.json', 'w') as f:
    json.dump({
        'loss_by_source': loss_by_source,
        'total_losses': len(all_loss_pids),
        'breakdown': results
    }, f, indent=2)
