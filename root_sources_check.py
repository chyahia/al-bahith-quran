# -*- coding: utf-8 -*-
"""
فحص الجذور بين القواعد (الأداة السابعة في تبويب الفحص، القسم 28 من سجل التطوير).
للقراءة فقط: لا يعدّل شيئًا.

يقارن الجذر المنسوب لكل كلمة (سورة، آية، رقم الكلمة) في ثلاثة مصادر:
  - root_words في quran.db (جذور QUL): البحث بالجذر في التبويب 1، وملف الجذر، والإحصاء العام.
  - word_lemmas في quran.db (المدونة 0.4): صيغ الجذر (اللمّات) في ملف الجذر.
  - words في quran_awzan.db (النسخة العربية المصحَّحة من المدونة): تبويب البحث بالوزن.
ترقيم quran.db يتبع نص Tanzil، وترقيم المدونة يدمج كلمتين في آيات معدودة («بعدما» في البقرة 181).
فيُحوَّل ترقيم قاعدة الأوزان إلى ترقيم quran.db في تلك الآيات بالقاعدة نفسها التي بُني بها word_lemmas
(build_lemmas.py): إزاحة ما بعد الكلمة المدموجة إذا زادت بها مطابقة الجذور. ثم المقارنة موضعًا بموضع.
وتُوحَّد الهمزة قبل المقارنة (أمن = امن)، لأن جدول الجذور يكتبها ألفًا.

الفئات:
  DIFF_ANALYSIS : جذران مختلفان يشتركان في حرفين فأكثر: اختلاف تحليل صرفي (ناس: نوس / أنس).
  DIFF_SUSPECT  : جذران لا يشتركان إلا في حرف أو لا شيء، أو جذر الكلمة في مصدر هو جذر جارتها في الآخر:
                  اشتباه خطأ ترقيم أو نسبة (يحتاج مراجعة).
  ONLY_QUL      : للكلمة جذر في root_words وليس لها جذر في قاعدة الأوزان.
  ONLY_AWZAN    : للكلمة جذر في قاعدة الأوزان وليس لها جذر في root_words.
"""
import os
import re
import sqlite3
import sys
from collections import Counter

from grammar_engine import MASAQ_MERGED_WORD_NO

HAMZA_RE = re.compile('[أإآءؤئ]')

CATEGORY_LABELS = {
    'DIFF_SUSPECT': 'اختلاف لا تفسّره الصرف: اشتباه ترقيم أو نسبة (يحتاج مراجعة)',
    'DIFF_ANALYSIS': 'اختلاف في التحليل الصرفي (الجذر نفسه بقراءتين)',
    'ONLY_QUL': 'للكلمة جذر في التبويبات 1 و3 و4 وحدها',
    'ONLY_AWZAN': 'للكلمة جذر في تبويب الوزن وحده',
}
ORDER = ['DIFF_SUSPECT', 'DIFF_ANALYSIS', 'ONLY_QUL', 'ONLY_AWZAN']


def _path(name):
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath('.')
    return os.path.join(base, name)


def _norm(r):
    return HAMZA_RE.sub('ا', (r or '').replace(' ', ''))


def run_root_sources_check():
    q = sqlite3.connect(_path('quran.db'))
    names = dict(q.execute('SELECT id, name FROM suras'))
    qul, qul_raw = {}, {}
    for s, a, loc, root in q.execute('SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral '
                                     'FROM root_words rw JOIN roots r ON rw.root_id = r.id'):
        try:
            k = (int(s), int(a), int(loc.split(':')[2]))
        except Exception:
            continue
        if k not in qul:
            qul[k] = _norm(root)
            qul_raw[k] = (root or '').replace(' ', '')
    lem = {(s, a, w): _norm(r) for s, a, w, r in
           q.execute("SELECT sura_id, aya_num, word_num, root FROM word_lemmas WHERE root IS NOT NULL AND root != ''")}
    q.close()

    path = _path('quran_awzan.db')
    if not os.path.exists(path):
        raise FileNotFoundError('لم يُعثر على quran_awzan.db في مجلد البرنامج')
    w = sqlite3.connect(path)
    awz, awz_raw, words = {}, {}, {}
    for s, a, wn, word, root in w.execute('SELECT sura, aya, word_no, word, root FROM words ORDER BY id'):
        k = (s, a, wn)
        if k not in awz:
            awz[k] = _norm(root)
            awz_raw[k] = root
            words[k] = word
    w.close()

    # مواءمة الترقيم في آيات الدمج (كما في build_lemmas.py)
    def agreement(s, a, shift_after):
        n = 0
        for (cs, ca, cw), r in awz.items():
            if (cs, ca) != (s, a):
                continue
            ww = cw + 1 if (shift_after is not None and cw > shift_after) else cw
            n += qul.get((s, a, ww)) == r
        return n
    shifts = {sa: m for sa, m in MASAQ_MERGED_WORD_NO.items() if agreement(*sa, m) > agreement(*sa, None)}
    if shifts:
        def mv(k):
            m = shifts.get(k[:2])
            return (k[0], k[1], k[2] + 1) if m is not None and k[2] > m else k
        awz = {mv(k): v for k, v in awz.items()}
        awz_raw = {mv(k): v for k, v in awz_raw.items()}
        words = {mv(k): v for k, v in words.items()}

    issues = []
    for k in sorted(qul.keys() | awz.keys()):
        r1, r3 = qul.get(k), awz.get(k)
        if r1 == r3:
            continue
        s, a, wn = k
        shifted = r3 and (qul.get((s, a, wn + 1)) == r3 or qul.get((s, a, wn - 1)) == r3)
        if r1 and r3:
            shared = sum((Counter(r1) & Counter(r3)).values())
            cat = 'DIFF_ANALYSIS' if shared >= 2 and not shifted else 'DIFF_SUSPECT'
        else:
            cat = 'ONLY_QUL' if r1 else 'ONLY_AWZAN'
        issues.append({'category': cat, 'sura_no': s, 'sura_name': names.get(s, str(s)), 'verse_no': a, 'word_no': wn,
                       'word': words.get(k, ''), 'root_qul': qul_raw.get(k, ''), 'root_lemmas': lem.get(k, ''),
                       'root_awzan': awz_raw.get(k, '')})

    # عدد مواضع كل جذر في كل مصدر، والجذور التي يختلف عددها
    c1, c2, c3 = Counter(qul.values()), Counter(lem.values()), Counter(awz.values())
    roots = []
    for r in sorted(set(c1) | set(c3), key=lambda x: -max(c1[x], c3[x])):
        if c1[r] != c3[r]:
            roots.append({'root': r, 'qul': c1[r], 'lemmas': c2[r], 'awzan': c3[r], 'diff': c3[r] - c1[r]})

    issues.sort(key=lambda x: (ORDER.index(x['category']), x['sura_no'], x['verse_no'], x['word_no']))
    cnt = Counter(i['category'] for i in issues)
    summary = {
        'positions_qul': len(qul), 'positions_lemmas': len(lem), 'positions_awzan': len(awz),
        'agree': sum(1 for k in qul.keys() & awz.keys() if qul[k] == awz[k]),
        'roots_differ': len(roots),
        'shifted_ayat': [f'{names.get(sa[0], sa[0])}:{sa[1]}' for sa in sorted(shifts)],
        **{k.lower(): cnt.get(k, 0) for k in ORDER},
    }
    return {'summary': summary, 'labels': CATEGORY_LABELS, 'issues': issues, 'roots': roots}


def export_root_sources_excel(result):
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    bold, fill = Font(name='Arial', bold=True, color='FFFFFF'), PatternFill('solid', start_color='1B5E20')

    def sheet(ws, headers, rows, widths):
        ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = bold, fill
        for r in rows:
            ws.append(r)
        for i, wd in enumerate(widths):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = wd
        ws.freeze_panes = 'A2'

    ws = wb.active
    ws.title = 'الجذور المختلفة العدد'
    sheet(ws, ['الجذر', 'المواضع في التبويبات 1 و3 و4 (QUL)', 'المواضع في اللمّات (المدونة 0.4)',
               'المواضع في تبويب الوزن', 'الفرق (الوزن − QUL)'],
          [[r['root'], r['qul'], r['lemmas'], r['awzan'], r['diff']] for r in result['roots']], [10, 30, 30, 22, 18])
    ws2 = wb.create_sheet('المواضع')
    sheet(ws2, ['الفئة', 'السورة', 'الآية', 'رقم الكلمة', 'الكلمة', 'جذر QUL', 'جذر اللمّات', 'جذر قاعدة الأوزان'],
          [[result['labels'][i['category']], i['sura_name'], i['verse_no'], i['word_no'], i['word'],
            i['root_qul'], i['root_lemmas'], i['root_awzan']] for i in result['issues']],
          [48, 12, 8, 10, 18, 12, 12, 16])
    return wb
