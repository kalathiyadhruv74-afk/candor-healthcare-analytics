import collections, re, json

ectopic_pids = set()
missed_abortion_pids = set()
de_dc_pids = set()
blighted_ovum_pids = set()
spontaneous_pids = set()
cardiac_absent_pids = set()
anomalous_pids = set()
iud_pids = set()
all_loss_pids = set()
delivery_pids = set()
total_pids = set()

with open('candor_healthcare (3).sql', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if line.startswith('INSERT INTO anc_history '):
            parts = line[len('INSERT INTO anc_history VALUES('):].split(',', 4)
            if len(parts) >= 3:
                try:
                    pid = int(parts[2].strip())
                    total_pids.add(pid)
                    low = line.lower()
                    
                    if any(t in low for t in ['lscs', 'ftnd', 'delivery', 'cesarean', 'live birth', 'baby boy', 'baby girl', 'delivered', '37 wks', '38 wks', '39 wks', '40 wks', '37 weeks', '38 weeks', '39 weeks', '40 weeks', '9 month']):
                        delivery_pids.add(pid)

                    is_loss = False
                    if 'ec_topic' in low or 'ectopic' in low:
                        m_ec = re.findall(r'"ec_topic":"(.*?)"', line)
                        if (m_ec and m_ec[0] not in ['null', 'no', 'none', 'false']) or 'ectopic' in low:
                            ectopic_pids.add(pid)
                            is_loss = True
                    if 'missed abortion' in low:
                        missed_abortion_pids.add(pid)
                        is_loss = True
                    if 'd&e' in low or 'd&c' in low or 'evacuation' in low:
                        de_dc_pids.add(pid)
                        is_loss = True
                    if 'blighted ovum' in low or 'anembryonic' in low:
                        blighted_ovum_pids.add(pid)
                        is_loss = True
                    if 'spontaneous abortion' in low or 'miscarriage' in low:
                        spontaneous_pids.add(pid)
                        is_loss = True
                    if 'cardiac activity absent' in low or 'no cardiac' in low:
                        cardiac_absent_pids.add(pid)
                        is_loss = True
                    if 'anomalous' in low or 'anencephaly' in low or 'anomaly' in low:
                        anomalous_pids.add(pid)
                        is_loss = True
                    if 'iud' in low or 'fetal demise' in low or 'intrauterine death' in low or 'stillbirth' in low:
                        iud_pids.add(pid)
                        is_loss = True

                    if is_loss:
                        all_loss_pids.add(pid)
                except:
                    pass

stats = {
    'total_anc_history_patients': len(total_pids),
    'delivery_patients': len(delivery_pids),
    'delivery_rate': round(len(delivery_pids) / len(total_pids) * 100, 1),
    'all_loss_patients': len(all_loss_pids),
    'loss_rate': round(len(all_loss_pids) / len(total_pids) * 100, 1),
    'ongoing_or_external': len(total_pids) - len(delivery_pids) - len(all_loss_pids),
    'ongoing_rate': round((len(total_pids) - len(delivery_pids) - len(all_loss_pids)) / len(total_pids) * 100, 1),
    'reasons': [
        {
            'name': 'Ectopic Pregnancy (Tubal/Extrauterine Implantation)',
            'patients': len(ectopic_pids),
            'pct_of_losses': round(len(ectopic_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Embryo implanted outside the uterine cavity (usually Fallopian tube), requiring urgent medical or laparoscopic intervention.'
        },
        {
            'name': 'Missed Abortion (Silent Embryonic Arrest)',
            'patients': len(missed_abortion_pids),
            'pct_of_losses': round(len(missed_abortion_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Fetus stopped developing and cardiac activity ceased without spontaneous uterine expulsion, identified via early transvaginal scan.'
        },
        {
            'name': 'D&E / D&C Uterine Evacuation',
            'patients': len(de_dc_pids),
            'pct_of_losses': round(len(de_dc_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Dilatation & Curettage or Dilatation & Evacuation performed to safely clear retained non-viable conception products.'
        },
        {
            'name': 'Blighted Ovum (Anembryonic Sac)',
            'patients': len(blighted_ovum_pids),
            'pct_of_losses': round(len(blighted_ovum_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'A gestational sac formed and attached to uterine wall, but the embryonic fetal pole failed to develop due to chromosomal issues.'
        },
        {
            'name': 'Spontaneous Miscarriage',
            'patients': len(spontaneous_pids),
            'pct_of_losses': round(len(spontaneous_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Natural early spontaneous pregnancy loss occurring before 12 weeks with bleeding and cramping.'
        },
        {
            'name': 'Fetal Cardiac Arrest / Absence',
            'patients': len(cardiac_absent_pids),
            'pct_of_losses': round(len(cardiac_absent_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Failure of fetal heart tube formation or cessation of heart beats during first trimester ultrasound assessment.'
        },
        {
            'name': 'Fetal Demise / IUD (Intrauterine Fetal Death)',
            'patients': len(iud_pids),
            'pct_of_losses': round(len(iud_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Late-stage fetal death occurring in second or third trimester before or during labor.'
        },
        {
            'name': 'Major Congenital / Structural Anomalies',
            'patients': len(anomalous_pids),
            'pct_of_losses': round(len(anomalous_pids) / len(all_loss_pids) * 100, 1),
            'clinical_explanation': 'Severe anatomical defects (e.g. anencephaly, severe neural tube defects) detected during 11-13 week NT or 18-20 week anomaly scans.'
        }
    ]
}

print(json.dumps(stats, indent=2))
with open('data/anc_outcome_breakdown.json', 'w') as out:
    json.dump(stats, out, indent=2)
