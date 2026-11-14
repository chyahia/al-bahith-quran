# -*- coding: utf-8 -*-
"""
تبويب «البحث بالوزن» (القسم 26 من سجل تطوير البرنامج).
قراءة فقط من quran_awzan.db (الأوزان) ومن quran.db (نصوص الآيات وأسماء السور).

quran_awzan.db مبنية بالسكربت build_wazn_db.py من ملف المدونة القرآنية (Quranic Arabic Corpus 0.4):
لكل كلمة لها جذر (اسم أو فعل) ثلاثة أوزان:
  - wazn_fi3l   : وزن الفعل بصيغة الماضي (فَعَلَ، أَفْعَلَ، تَفَاعَلَ ...)، من تصنيف المدونة للصيغ.
  - wazn_mufrad : وزن الاسم، وجمع السلامة والمثنى مردودان إلى المفرد (كافِرُون ← فاعِل).
  - wazn        : الوزن كما وردت الكلمة، دون السوابق واللواحق وعلامة الإعراب (يَتَسَاءَلُونَ ← يَتَفَاعَل).
ترقيم الكلمات (word_no) ترقيم المدونة، ويُواءَم هنا مع كلمات text_tashkeel لتمييز الكلمة داخل الآية.
"""
import base64
import io
import os
import re
import sqlite3
import sys
from collections import Counter

import distribution

HARAKAT_RE = re.compile('[ً-ْٰ]')
LETTER_RE = re.compile('[ء-يٱ]')
NON_LETTER_RE = re.compile('[^ء-يٱ]')

# نوع البحث ← (العمود، الشرط، الوصف)
KINDS = {
    'فعل':  ('wazn_fi3l',   "pos = 'V'",                       'أوزان الأفعال (بصيغة الماضي)'),
    'اسم':  ('wazn_mufrad', "pos = 'N' AND category != 'علم'", 'أوزان الأسماء والصفات والمشتقات'),
    'صيغة': ('wazn',        '1',                               'الصيغة كما وردت (المضارع والجمع ...)'),
}
CATEGORIES = ['اسم', 'صفة', 'اسم فاعل', 'اسم مفعول', 'مصدر', 'فعل']
MECCAN_MAX_REV = 86     # المكي: ترتيب نزوله 86 فما دون، كبقية التبويبات


def _path(name):
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath('.')
    return os.path.join(base, name)


def _bare(s):
    return HARAKAT_RE.sub('', s or '')


def _conn(name):
    path = _path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f'لم يُعثر على {name} في مجلد البرنامج')
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.create_function('bare', 1, _bare, deterministic=True)
    return c


# ---------------------------------------------------------------- مواءمة ترقيم المدونة مع كلمات النص المشكول
def _strip_basmala_tokens(tokens, sura, aya):
    if aya == 1 and sura not in (1, 9) and len(tokens) > 4 and NON_LETTER_RE.sub('', tokens[0]) == 'بسم':
        return tokens[4:]
    return tokens


def _word_groups(tokens, n_corpus):
    """يرد قائمة: لكل كلمة في المدونة فهارس كلماتها في النص المشكول (علامات الوقف لا تُعد كلمات).
    «يَا أَيُّهَا» و«وَيَا قَوْمِ» و«هَا أَنْتُمْ» و«بَعْدَ مَا» كلمتان في النص وكلمة واحدة في المدونة.
    يرد None إن لم تتطابق الأعداد."""
    groups = [[i] for i, t in enumerate(tokens) if LETTER_RE.search(t)]
    excess = len(groups) - n_corpus
    if excess > 0:
        out, k = [], 0
        while k < len(groups):
            w = NON_LETTER_RE.sub('', tokens[groups[k][0]])
            nxt = NON_LETTER_RE.sub('', tokens[groups[k + 1][0]]) if k + 1 < len(groups) else ''
            if excess > 0 and k + 1 < len(groups) and (w in ('يا', 'ويا', 'فيا', 'ها', 'وها', 'فها') or
                                                       (w == 'بعد' and nxt == 'ما')):
                out.append(groups[k] + groups[k + 1]); k += 2; excess -= 1
            else:
                out.append(groups[k]); k += 1
        groups = out
    return groups if len(groups) == n_corpus else None


# ---------------------------------------------------------------- البيانات الوصفية للواجهة
def wazn_meta():
    c = _conn('quran_awzan.db')
    lists = {}
    for kind in KINDS:
        lists[kind] = [[r['wazn'], r['count']] for r in c.execute(
            'SELECT wazn, count FROM awzan WHERE kind = ? ORDER BY count DESC, wazn', (kind,))]
    n_words = c.execute('SELECT COUNT(*) FROM words').fetchone()[0]
    c.close()
    q = _conn('quran.db')
    suras = [dict(r) for r in q.execute('SELECT id, name FROM suras ORDER BY id')]
    q.close()
    return {
        'kinds': [{'value': k, 'label': v[2]} for k, v in KINDS.items()],
        'lists': lists,
        'categories': CATEGORIES,
        'suras': suras,
        'n_words': n_words,
    }


# ---------------------------------------------------------------- البحث
def search_wazn(f, rev_order):
    kind = f.get('kind') if f.get('kind') in KINDS else 'اسم'
    col, cond, _ = KINDS[kind]
    wazn = ' '.join((f.get('wazn') or '').split())
    if not wazn:
        return {'error': 'اختر وزنًا أو اكتبه'}

    # بالحركات: مطابقة تامة؛ دونها: مطابقة الحروف فقط (فاعل تشمل فاعِل وفاعَل)
    if HARAKAT_RE.search(wazn):
        where, params = f'{col} = ?', [wazn]
    else:
        where, params = f'bare({col}) = ?', [wazn]
    where += f' AND {cond}'
    cat = f.get('category') or 'all'
    if cat != 'all':
        where += ' AND category = ?'; params.append(cat)
    sura = f.get('sura') or 'all'
    if sura != 'all':
        where += ' AND sura = ?'; params.append(int(sura))
    period = f.get('period') or 'all'

    c = _conn('quran_awzan.db')
    rows = c.execute(f'''SELECT sura, aya, word_no, word, root, lemma, category, {col} AS w, confidence
                         FROM words WHERE {where} ORDER BY sura, aya, word_no''', params).fetchall()
    if period != 'all':
        meccan = period == 'meccan'
        rows = [r for r in rows if (rev_order.get(r['sura'], 999) <= MECCAN_MAX_REV) == meccan]
    by_aya = {}
    for r in rows:
        by_aya.setdefault((r['sura'], r['aya']), []).append(r)
    n_corpus = {}
    if by_aya:
        for r in c.execute('SELECT sura, aya, text FROM ayat'):
            if (r['sura'], r['aya']) in by_aya:
                n_corpus[(r['sura'], r['aya'])] = len(r['text'].split(' '))
    c.close()

    q = _conn('quran.db')
    names = {r['id']: r['name'] for r in q.execute('SELECT id, name FROM suras')}
    texts = {(r['sura_id'], r['aya_num']): r['text_tashkeel']
             for r in q.execute('SELECT sura_id, aya_num, text_tashkeel FROM ayas') if (r['sura_id'], r['aya_num']) in by_aya}
    q.close()

    results, sura_stats = [], {}
    wazn_cnt, cat_cnt, root_cnt = Counter(), Counter(), Counter()
    for (s, a), ws in by_aya.items():
        tokens = _strip_basmala_tokens(texts.get((s, a), '').split(), s, a)
        groups = _word_groups(tokens, n_corpus.get((s, a), -1))
        hl, words = [], []
        for w in ws:
            shown = w['word']
            if groups and 1 <= w['word_no'] <= len(groups):
                idx = groups[w['word_no'] - 1]
                hl.extend(idx)
                shown = ' '.join(tokens[i] for i in idx)
            words.append({'word': shown, 'root': w['root'], 'lemma': w['lemma'], 'category': w['category'],
                          'wazn': w['w'], 'approx': (w['confidence'] or 0) < 0.7})
            wazn_cnt[w['w']] += 1
            cat_cnt[w['category']] += 1
            root_cnt[w['root']] += 1
        results.append({'sura': s, 'sura_name': names.get(s, str(s)), 'aya': a,
                        'tokens': tokens, 'hl': sorted(set(hl)), 'words': words})
        st = sura_stats.setdefault(s, {'sura_id': s, 'name': names.get(s, str(s)), 'occurrences': 0, 'ayahs': 0})
        st['occurrences'] += len(ws)
        st['ayahs'] += 1

    label = f"{KINDS[kind][2]}: {wazn}"
    if cat != 'all':
        label += f' — نوع الكلمة: {cat}'
    if sura != 'all':
        label += f" — السورة: {names.get(int(sura), sura)}"
    if period != 'all':
        label += ' — ' + ('المكي' if period == 'meccan' else 'المدني')

    chart = distribution.calculate_distribution(
        [{'sura_id': x['sura'], 'aya_num': x['aya'], 'occ': len(x['words'])} for x in results], rev_order)
    return {
        'kind': kind,
        'wazn': wazn,
        'label': label,
        'results': results,
        'ayahs': len(results),
        'occurrences': len(rows),
        'top_suras': sorted(sura_stats.values(), key=lambda x: (-x['occurrences'], -x['ayahs'], x['sura_id'])),
        'by_wazn': wazn_cnt.most_common(),          # يفيد عند البحث دون حركات
        'by_category': cat_cnt.most_common(),
        'top_roots': root_cnt.most_common(),
        'chart': chart,
    }


# ---------------------------------------------------------------- تقرير Word (بطريقة تقرير البحث البلاغي)
def create_wazn_docx(f, rev_order, charts=None, f2=None):
    """تقرير Word: البحث وعدده، ثم رسوم التوزيع وجداولها، ثم أكثر السور والجذور، ثم الآيات بتمييز الكلمة.
    وفي المقارنة (f2): الوزنان معًا، ولكلٍّ منهما لون في الآيات وعمود في الجداول."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Inches

    charts = charts or {}
    data = search_wazn(f, rev_order)
    if data.get('error'):
        raise ValueError(data['error'])
    data2 = search_wazn(f2, rev_order) if f2 else None
    if data2 and data2.get('error'):
        raise ValueError(data2['error'])
    sets = [data] + ([data2] if data2 else [])
    GREEN, GREY, RED = RGBColor(27, 94, 32), RGBColor(110, 110, 110), RGBColor(183, 28, 28)
    BLUE = RGBColor(13, 71, 161)
    HL = [('yellow', RED), ('cyan', BLUE)]          # لون التظليل ولون الخط للوزن الأول والثاني
    RLM = '\u200f'
    doc = Document()
    sect = doc.sections[0]._sectPr
    if sect.find(qn('w:bidi')) is None:
        sect.append(OxmlElement('w:bidi'))
    tfl = doc.settings.element.find(qn('w:themeFontLang'))
    if tfl is not None:
        tfl.set(qn('w:bidi'), 'ar-SA')

    def rtl_par(p):
        pPr = p._p.get_or_add_pPr()
        pPr.append(OxmlElement('w:bidi'))
        mark = OxmlElement('w:rPr')
        mark.append(OxmlElement('w:rtl'))
        pPr.append(mark)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT   # في الفقرة ثنائية الاتجاه: LEFT = اليمين

    def run(p, text, size=12, bold=False, color=None, font=None, highlight=None):
        r = p.add_run(RLM + str(text) + RLM)
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.rtl = True
        if color:
            r.font.color.rgb = color
        rPr = r._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.append(rFonts)
        for k in ('w:cs', 'w:ascii', 'w:hAnsi'):
            rFonts.set(qn(k), font or 'Arial')
        rFonts.set(qn('w:hint'), 'cs')
        if bold:
            rPr.append(OxmlElement('w:bCs'))
        szCs = OxmlElement('w:szCs')
        szCs.set(qn('w:val'), str(int(size * 2)))
        rPr.append(szCs)
        if highlight:
            hl = OxmlElement('w:highlight')
            hl.set(qn('w:val'), highlight if isinstance(highlight, str) else 'yellow')
            rPr.append(hl)
        return r

    def para(text='', size=12, bold=False, color=None, font=None):
        p = doc.add_paragraph()
        rtl_par(p)
        if text:
            run(p, text, size, bold, color, font)
        return p

    def table(headers, rows):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = 'Table Grid'
        t._tbl.tblPr.append(OxmlElement('w:bidiVisual'))
        for i, h in enumerate(headers):
            c0 = t.rows[0].cells[i].paragraphs[0]
            rtl_par(c0)
            run(c0, h, 11, True)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                c0 = cells[i].paragraphs[0]
                rtl_par(c0)
                run(c0, v, 11)
        doc.add_paragraph()

    def picture(b64):
        if b64 and ',' in b64:
            try:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(io.BytesIO(base64.b64decode(b64.split(',', 1)[1])), width=Inches(6.3))
            except Exception:
                pass

    para('الباحث في القرآن الكريم — ' + ('مقارنة الأوزان الصرفية' if data2 else 'البحث بالوزن الصرفي'), 16, True, GREEN)
    for g, d in enumerate(sets):
        p = para()
        if data2:
            run(p, f'الوزن {"الأول" if g == 0 else "الثاني"} ', 12, True, HL[g][1], highlight=HL[g][0])
            run(p, ' ', 12)
        run(p, 'البحث: ' + d['label'], 12)
        para(f"النتائج: {d['occurrences']} موضعًا في {d['ayahs']} آية", 12, True)
        if len(d['by_wazn']) > 1:
            para('الأوزان المطابقة: ' + '، '.join(f'{w} ({n})' for w, n in d['by_wazn']), 11)
        if d['by_category']:
            para('نوع الكلمة: ' + '، '.join(f'{c} ({n})' for c, n in d['by_category']), 11)
    # الآيات مدموجة بترتيب المصحف: لكل آية كلمات الوزنين
    merged = {}
    for g, d in enumerate(sets):
        for x in d['results']:
            r = merged.setdefault((x['sura'], x['aya']), {'sura_name': x['sura_name'], 'aya': x['aya'], 'tokens': x['tokens'],
                                                           'hl': [set(), set()], 'words': [[], []]})
            r['hl'][g] = set(x['hl'])
            r['words'][g] = x['words']
    if data2:
        both = sum(1 for r in merged.values() if r['words'][0] and r['words'][1])
        para(f'آيات فيها الوزنان معًا: {both}', 12, True, GREEN)
    para('الأوزان مستخرجة آليًا من التحليل الصرفي للمدونة القرآنية؛ والكلمة الموسومة بـ ≈ وزنها تقريبي يحتاج مراجعة.',
         10, False, GREY)
    para()

    # ---- رسوم التوزيع وجداولها (كما رسمها المتصفح بالوحدة والقياس المختارين)
    for kind, title in (('juz', 'التوزيع بحسب الأجزاء'), ('mushaf', 'التوزيع بحسب ترتيب المصحف'),
                        ('revelation', 'التوزيع بحسب ترتيب النزول')):
        ch = charts.get(kind)
        para(title, 14, True, GREEN)
        if isinstance(ch, dict) and ch.get('headers'):
            picture(ch.get('img'))
            if ch.get('unit'):
                para('الوحدة: ' + ch['unit'], 10, False, GREY)
            table(ch['headers'], ch.get('rows') or [])
            if ch.get('note'):
                para(ch['note'], 10, False, GREY)
        else:                                   # بلا متصفح: جدول المواضع والآيات من الخادم
            first = 'الجزء' if kind == 'juz' else 'القطاع'
            labels = data['chart'][kind]['labels']
            heads, cols = [first], []
            for d in sets:
                c = d['chart'][kind]
                pre = (d['wazn'] + ': ') if data2 else ''
                heads += [pre + 'المواضع', pre + 'الآيات']
                cols += [c['occ'], c['counts']]
            rows = [[('الجزء ' + lab) if kind == 'juz' else lab] + [col[i] for col in cols] for i, lab in enumerate(labels)]
            rows.append(['المجموع'] + [sum(col) for col in cols])
            table(heads, rows)

    # ---- أكثر السور ورودًا (كل السور)
    if not data2 and data['top_suras']:
        para('أكثر السور ورودًا', 14, True, GREEN)
        tot = sum(x['occurrences'] for x in data['top_suras']) or 1
        table(['#', 'السورة', 'المواضع', 'الآيات', 'النسبة'],
              [[i, x['name'], x['occurrences'], x['ayahs'], f"{100 * x['occurrences'] / tot:.1f}%"]
               for i, x in enumerate(data['top_suras'], 1)])
    elif data2:
        m = {}
        for g, d in enumerate(sets):
            for x in d['top_suras']:
                m.setdefault(x['sura_id'], [x['name'], 0, 0])[g + 1] = x['occurrences']
        rows = sorted(m.values(), key=lambda r: -(r[1] + r[2]))
        if rows:
            para('أكثر السور ورودًا', 14, True, GREEN)
            table(['#', 'السورة', data['wazn'], data2['wazn'], 'المجموع'],
                  [[i, r[0], r[1], r[2], r[1] + r[2]] for i, r in enumerate(rows, 1)])

    # ---- أكثر الجذور ورودًا على الوزن (لكل وزن جدول)
    for d in sets:
        if d['top_roots']:
            para('أكثر الجذور ورودًا على ' + (f'«{d["wazn"]}»' if data2 else 'هذا الوزن'), 14, True, GREEN)
            tot = sum(n for _, n in d['top_roots']) or 1
            table(['#', 'الجذر', 'المواضع', 'النسبة'],
                  [[i, r, n, f'{100 * n / tot:.1f}%'] for i, (r, n) in enumerate(d['top_roots'], 1)])

    # ---- الآيات: الكلمة مميزة داخل الآية (بلون وزنها)، ثم مذكورة بعدها بوزنها وجذرها
    para('الآيات', 14, True, GREEN)
    if data2:
        p = para()
        run(p, 'الوزن الأول', 11, True, HL[0][1], highlight=HL[0][0])
        run(p, ' ، ', 11)
        run(p, 'الوزن الثاني', 11, True, HL[1][1], highlight=HL[1][0])
    for i, ((s_, a_), x) in enumerate(sorted(merged.items()), 1):
        p = para()
        run(p, f'{i}. ﴿ ', 16, False, None, 'Traditional Arabic')
        for k, t in enumerate(x['tokens']):
            g = 0 if k in x['hl'][0] else (1 if k in x['hl'][1] else None)
            if g is None:
                run(p, t, 16, False, None, 'Traditional Arabic')
            else:
                run(p, t, 16, True, HL[g][1], 'Traditional Arabic', highlight=HL[g][0])
            run(p, ' ', 16, False, None, 'Traditional Arabic')
        run(p, '﴾ ', 16, False, None, 'Traditional Arabic')
        run(p, f"[{x['sura_name']}: {x['aya']}]", 11, True, GREY)
        for g in (0, 1):
            ws = x['words'][g]
            if not ws:
                continue
            p2 = para()
            run(p2, 'الكلمة: ' if len(ws) == 1 else 'الكلمات: ', 11, True, HL[g][1] if data2 else GREEN)
            for j, w in enumerate(ws):
                if j:
                    run(p2, '، ', 11)
                run(p2, w['word'], 13, True, None, 'Traditional Arabic')
                run(p2, f" ({'≈ ' if w['approx'] else ''}{w['wazn']}، جذر: {w['root']}، {w['category']})", 10, False, GREY)
    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream
