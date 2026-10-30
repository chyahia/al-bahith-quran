# -*- coding: utf-8 -*-
"""
توزيع النتائج على المصحف للرسوم البيانية (القسم 25 من سجل تطوير البرنامج). مشترك بين التبويبات.

ثلاثة محاور:
  - juz:        الأجزاء الثلاثون (متقاربة في طول النص: 2484–2976 كلمة)، فيكفي فيها العدد. الافتراضي.
  - mushaf:     القطاعات العشرة بترتيب المصحف (غير متساوية: 60–1596 آية).
  - revelation: القطاعات العشرة بترتيب النزول.
ولكل محور: counts = عدد الآيات، occ = عدد المواضع، totals = عدد آيات كل قسم (مقام «لكل 100 آية»).
والصف يحمل sura_id، وaya_num (لازم للأجزاء)، وocc (عدد مواضعه، 1 إن غاب).
"""
import os
import sqlite3
import sys

MUSHAF_BINS = [(1, 11, "الفاتحة-هود"), (12, 22, "يوسف-الحج"), (23, 34, "المؤمنون-سبأ"), (35, 45, "فاطر-الجاثية"),
               (46, 57, "الأحقاف-الحديد"), (58, 68, "المجادلة-القلم"), (69, 79, "الحاقة-النازعات"), (80, 91, "عبس-الشمس"),
               (92, 102, "الليل-التكاثر"), (103, 114, "العصر-الناس")]
REV_BINS = [(1, 11, "العلق-الضحى"), (12, 22, "الشرح-الإخلاص"), (23, 34, "النجم-ق"), (35, 45, "البلد-طه"),
            (46, 57, "الواقعة-لقمان"), (58, 68, "سبأ-الغاشية"), (69, 79, "الكهف-المعارج"), (80, 91, "النبأ-الممتحنة"),
            (92, 102, "النساء-النور"), (103, 114, "الحج-النصر")]
# بدايات الأجزاء (سورة، آية) بحسب تقسيم Tanzil
JUZ_STARTS = [(1, 1), (2, 142), (2, 253), (3, 93), (4, 24), (4, 148), (5, 83), (6, 111), (7, 88), (8, 41),
              (9, 93), (11, 6), (12, 53), (15, 1), (17, 1), (18, 75), (21, 1), (23, 1), (25, 21), (27, 56),
              (29, 46), (33, 31), (36, 28), (39, 32), (41, 47), (46, 1), (51, 31), (58, 1), (67, 1), (78, 1)]
JUZ_LABELS = [str(i) for i in range(1, 31)]

_totals_cache = None


def juz_of(sura, aya):
    j = 0
    for i, (s, a) in enumerate(JUZ_STARTS):
        if (sura, aya) >= (s, a):
            j = i
        else:
            break
    return j


def _bin_of(bins, pos):
    for i, (lo, hi, _) in enumerate(bins):
        if lo <= pos <= hi:
            return i
    return None


def _db_path():
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath('.')
    return os.path.join(base, 'quran.db')


def section_totals(rev_order):
    """عدد آيات كل قسم في المحاور الثلاثة (يُحسب مرة من quran.db)."""
    global _totals_cache
    if _totals_cache is None:
        conn = sqlite3.connect(_db_path())
        counts = dict(conn.execute('SELECT sura_id, COUNT(*) FROM ayas GROUP BY sura_id').fetchall())
        conn.close()
        mus, rev, juz = [0] * 10, [0] * 10, [0] * 30
        for s, n in counts.items():
            mus[_bin_of(MUSHAF_BINS, s)] += n
            rev[_bin_of(REV_BINS, rev_order.get(s, 1))] += n
            for a in range(1, n + 1):
                juz[juz_of(s, a)] += 1
        _totals_cache = {'mushaf': mus, 'revelation': rev, 'juz': juz}
    return _totals_cache


def calculate_distribution(rows, rev_order):
    """rows: [{'sura_id', 'aya_num'?, 'occ'?}] -> {'mushaf'|'revelation'|'juz': {labels, counts, occ, totals}}."""
    tot = section_totals(rev_order)
    out = {
        'mushaf': {'labels': [b[2] for b in MUSHAF_BINS], 'counts': [0] * 10, 'occ': [0] * 10, 'totals': tot['mushaf']},
        'revelation': {'labels': [b[2] for b in REV_BINS], 'counts': [0] * 10, 'occ': [0] * 10, 'totals': tot['revelation']},
        'juz': {'labels': JUZ_LABELS, 'counts': [0] * 30, 'occ': [0] * 30, 'totals': tot['juz']},
    }
    for r in rows:
        s = int(r['sura_id'])
        occ = int(r.get('occ') or 1)
        a = r.get('aya_num')
        for kind, b in (('mushaf', _bin_of(MUSHAF_BINS, s)), ('revelation', _bin_of(REV_BINS, rev_order.get(s, 1))),
                        ('juz', juz_of(s, int(a)) if a is not None else None)):
            if b is not None:
                out[kind]['counts'][b] += 1
                out[kind]['occ'][b] += occ
    return out


def positions_distribution(positions, rev_order):
    """مواضع مفردة [(سورة، آية)] -> لكل محور: occ (المواضع) وcounts (الآيات المختلفة)."""
    per_aya = {}
    for s, a in positions:
        per_aya[(int(s), int(a))] = per_aya.get((int(s), int(a)), 0) + 1
    return calculate_distribution([{'sura_id': s, 'aya_num': a, 'occ': n} for (s, a), n in per_aya.items()], rev_order)
