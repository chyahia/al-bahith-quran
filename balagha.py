# -*- coding: utf-8 -*-
"""
«البحث البلاغي» (القسم 22 من سجل تطوير البرنامج). قراءة فقط من balagha.db (يبنيه build_balagha_db.py)
ومن quran.db (نصوص الآيات وأسماء السور).

المفسّرون يُقرؤون من جدول sources (الصابوني، الزمخشري، ابن عاشور...)، فلا يُعدَّل هذا الملف عند إضافة تفسير.

البحث:
  - الصورة: نوع من الستة، أو «كل المجازات» (استعارة + مرسل + عقلي + غير محدد)، أو «كل الصور».
  - المصدر (يُبنى من المفسّرين الموجودين):
      one:K          ما ذكره المفسّر K
      any            ما ذكره أيٌّ منهم
      all:K1,K2[,..] اتفقوا عليها: الآية فيها الصورة المختارة عند كلٍّ منهم
      only:K         انفرد به K: عنده، وليست عند أيٍّ من الباقين
    الموازنة بالآية. وكل اتفاق أو انفراد يُحصر في الآيات التي قرأها كل المفسّرين الداخلين فيه
    (ملف لم يكتمل، كابن عاشور، له نطاق مقروء في sources.coverage_json).
  - النطاق: سورة، والمكي أو المدني (ترتيب النزول ≤ 86 كبقية التبويبات).
  - الحكم: «إثبات» وحده افتراضيًا، ويمكن إظهار الاحتمالات.
  - فلاتر المفسّر: الوظيفة الحجاجية (رأسها)، اعتراض ابن المنيّر، الموقف من الكشاف؛ يُطبَّق كلٌّ منها على
    صفوف المفسّرين الذين في ملفهم ذلك العمود، ولا يمسّ صفوف غيرهم.
  - نص حر في اللفظ وعبارة المفسّر والملاحظة والوظيفة.
"""
import io
import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from grammar_engine import get_db_connection

MAIN_TYPES = ['تشبيه', 'مجاز مرسل', 'مجاز عقلي', 'استعارة', 'كناية', 'مجاز (غير محدد)']
TYPE_GROUPS = {
    'ALL_MAJAZ': ['استعارة', 'مجاز مرسل', 'مجاز عقلي', 'مجاز (غير محدد)'],
    'ALL': MAIN_TYPES,
}
TYPE_LABELS = {'ALL_MAJAZ': 'كل المجازات', 'ALL': 'كل الصور'}
FILTER_COLS = {'function': 'function_head', 'ibn': 'ibn_munayyir', 'stance': 'kashaf_stance'}
FILTER_SRC_COL = {'function': 'function', 'ibn': 'ibn_munayyir', 'stance': 'kashaf_stance'}
MECCAN_MAX_REV = 86

_DIAC = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')


def _norm(x):
    x = _DIAC.sub('', str(x or ''))
    x = re.sub('[ٱآ]', 'ا', x)
    x = re.sub('[ءأإؤئ]', '', x)
    return x.replace('ى', 'ي').replace('ة', 'ه')


def _conn():
    c = get_db_connection('balagha.db')
    try:
        c.execute('SELECT 1 FROM images LIMIT 1')
        c.execute('SELECT coverage_json FROM sources LIMIT 1')
    except Exception:
        c.close()
        raise RuntimeError('قاعدة balagha.db غير موجودة أو قديمة: شغّل build_balagha_db.py بجانب app.py.')
    return c


def _sources(c):
    out = []
    for r in c.execute('SELECT id, name, book, coverage_json, filters_json FROM sources ORDER BY ord'):
        cov = json.loads(r['coverage_json']) if r['coverage_json'] else None
        out.append({'key': r['id'], 'name': r['name'], 'book': r['book'],
                    'coverage': {int(k): v for k, v in cov.items()} if cov is not None else None,
                    'filters': json.loads(r['filters_json'] or '[]')})
    return out


def _mode_list(srcs):
    """خيارات قائمة المصدر بمجموعاتها."""
    keys = [s['key'] for s in srcs]
    name = {s['key']: s['name'] for s in srcs}
    groups = [{'label': 'مفسّر واحد', 'options': [{'value': 'one:' + k, 'label': name[k]} for k in keys]}]
    if len(keys) > 1:
        groups.append({'label': 'المجموع', 'options': [{'value': 'any', 'label': 'أيٌّ منهم' if len(keys) > 2 else 'أحدهما أو كلاهما'}]})
        agree = []
        for n in range(len(keys), 1, -1):
            for combo in combinations(keys, n):
                lab = ('اتفق عليها ' + ('الثلاثة' if n == 3 else 'الجميع')) if n == len(keys) and n > 2 else \
                      'اتفق ' + ' و'.join(name[k] for k in combo)
                agree.append({'value': 'all:' + ','.join(combo), 'label': lab})
        groups.append({'label': 'الاتفاق', 'options': agree})
        groups.append({'label': 'الانفراد', 'options': [{'value': 'only:' + k, 'label': 'انفرد به ' + name[k]} for k in keys]})
    return groups


def _mode_label(mode, srcs):
    for g in _mode_list(srcs):
        for o in g['options']:
            if o['value'] == mode:
                return o['label']
    return mode


def _mode_sources(mode, srcs):
    """(المفسّرون الذين تُعرض صفوفهم، المفسّرون الداخلون في الحصر بالنطاق المقروء)."""
    keys = [s['key'] for s in srcs]
    if mode.startswith('one:'):
        k = mode[4:]
        return [k], [k]
    if mode.startswith('all:'):
        ks = [k for k in mode[4:].split(',') if k in keys]
        return ks, ks
    if mode.startswith('only:'):
        return [mode[5:]], keys
    return keys, []         # any: لا حصر


def balagha_meta(rev_order=None):
    c = _conn()
    srcs = _sources(c)
    filt = {}
    for fkey, col in FILTER_COLS.items():
        per = {}
        for s in srcs:
            vals = [r[0] for r in c.execute(f"SELECT {col} FROM images WHERE source=? AND {col} IS NOT NULL "
                                            f"GROUP BY {col} ORDER BY COUNT(*) DESC", (s['key'],))]
            if vals:
                per[s['key']] = vals
        filt[fkey] = per
    counts = {s: n for s, n in c.execute("SELECT source, COUNT(*) FROM images WHERE hukm='إثبات' GROUP BY source")}
    outside = [[r[0], r[1], r[2]] for r in c.execute('SELECT source, kind, COUNT(*) FROM outside GROUP BY source, kind')]
    meta = dict(c.execute('SELECT key, value FROM meta').fetchall())
    c.close()
    q = get_db_connection('quran.db')
    suras = [{'id': r['id'], 'name': r['name']} for r in q.execute('SELECT id, name FROM suras ORDER BY id')]
    q.close()
    names = {s['id']: s['name'] for s in suras}
    q = get_db_connection('quran.db')
    aya_counts = {str(r[0]): r[1] for r in q.execute('SELECT sura_id, COUNT(*) FROM ayas GROUP BY sura_id')}
    q.close()
    for s in srcs:
        s['coverage_text'] = _coverage_text(s['coverage'], names)
        s['coverage'] = None if s['coverage'] is None else {str(k): v for k, v in s['coverage'].items()}
    return {'sources': srcs, 'modes': _mode_list(srcs), 'filters': filt, 'counts': counts, 'outside': outside,
            'built_at': meta.get('built_at'), 'suras': suras, 'aya_counts': aya_counts, 'types': MAIN_TYPES, 'type_groups': TYPE_LABELS,
            'rev_order': rev_order or {}}


def _coverage_text(cov, names):
    """«الفاتحة – الأنفال 40» لنطاق متصل من أول المصحف، وإلا قائمة السور."""
    if cov is None:
        return None
    suras = sorted(cov)
    if not suras:
        return 'لا شيء'
    last = suras[-1]
    q = get_db_connection('quran.db')
    counts = dict(q.execute('SELECT sura_id, COUNT(*) FROM ayas GROUP BY sura_id').fetchall())
    q.close()
    contiguous = suras == list(range(1, last + 1)) and all(cov[s] >= counts.get(s, 0) for s in suras[:-1])
    if contiguous:
        tail = names.get(last, str(last)) + ('' if cov[last] >= counts.get(last, 0) else f' {cov[last]}')
        return f'{names.get(1, "الفاتحة")} – {tail}'
    return '، '.join(f"{names.get(s, s)}{'' if cov[s] >= counts.get(s, 0) else ' (حتى ' + str(cov[s]) + ')'}" for s in suras)


def _sura_ok(s, f, rev_order):
    if f.get('sura') not in (None, '', 'all') and int(f['sura']) != s:
        return False
    period = f.get('period', 'all')
    if period == 'meccan' and rev_order.get(s, 1) > MECCAN_MAX_REV:
        return False
    if period == 'medinan' and rev_order.get(s, 1) <= MECCAN_MAX_REV:
        return False
    return True


def _row_ok(r, f, types, text_n, src_filters):
    if r['main_type'] not in types:
        return False
    if not f.get('include_ihtimal') and r['hukm'] != 'إثبات':
        return False
    for fkey, col in FILTER_COLS.items():
        v = f.get(fkey, 'all')
        # يُطبَّق الفلتر على صفوف المفسّر الذي في ملفه هذا العمود، ولا يمسّ غيره
        if v != 'all' and FILTER_SRC_COL[fkey] in src_filters.get(r['source'], []) and r[col] != v:
            return False
    if text_n:
        hay = _norm(' '.join(str(r[k] or '') for k in ('lafz', 'sub_type', 'note', 'function')))
        if text_n not in hay:
            return False
    return True


def _covered(cov, s, a):
    return cov is None or a <= cov.get(s, 0)


def search_balagha(f, rev_order):
    c = _conn()
    srcs = _sources(c)
    rows = c.execute('SELECT id, source, sura_id, aya_from, aya_to, main_type, hukm, function_head, ibn_munayyir, '
                     'kashaf_stance, lafz, sub_type, note, function FROM images').fetchall()
    c.close()
    keys = [s['key'] for s in srcs]
    name = {s['key']: s['name'] for s in srcs}
    cov = {s['key']: s['coverage'] for s in srcs}
    src_filters = {s['key']: s['filters'] for s in srcs}

    mode = f.get('source') or ('one:' + keys[0] if keys else 'any')
    if mode != 'any' and not any(o['value'] == mode for g in _mode_list(srcs) for o in g['options']):
        mode = 'any'
    show, restrict = _mode_sources(mode, srcs)
    ttype = f.get('type', 'ALL')
    types = set(TYPE_GROUPS.get(ttype, [ttype]))
    text_n = ' '.join(_norm(f.get('text', '')).split())

    match = defaultdict(lambda: defaultdict(list))
    aya_to = {}
    for r in rows:
        s, a = r['sura_id'], r['aya_from']
        if r['source'] not in keys or not _sura_ok(s, f, rev_order):
            continue
        if _row_ok(r, f, types, text_n, src_filters):
            match[(s, a)][r['source']].append(r)
            aya_to[(s, a)] = max(aya_to.get((s, a), a), r['aya_to'])

    has = {k: {key for key, v in match.items() if v[k]} for k in keys}
    if mode == 'any':
        result_keys = set().union(*has.values()) if has else set()
    elif mode.startswith('one:'):
        result_keys = has.get(show[0], set())
    elif mode.startswith('all:'):
        result_keys = set.intersection(*(has[k] for k in show)) if show else set()
    else:   # only:
        k = show[0]
        result_keys = has[k] - set().union(*(has[o] for o in keys if o != k))
    # حصر الاتفاق والانفراد في النطاق الذي قرأه كل المفسّرين الداخلين فيه
    limited = [k for k in restrict if cov.get(k) is not None] if mode.startswith(('all:', 'only:')) else []
    if limited:
        result_keys = {x for x in result_keys if all(_covered(cov[k], *x) for k in limited)}
    note = ''
    if limited:
        names_q = {}
        q = get_db_connection('quran.db')
        names_q = {r['id']: r['name'] for r in q.execute('SELECT id, name FROM suras')}
        q.close()
        note = 'المقارنة مقصورة على ما قُرئ من: ' + '؛ '.join(
            f"{name[k]} ({_coverage_text(cov[k], names_q)})" for k in limited)

    result_keys = sorted(result_keys)
    q = get_db_connection('quran.db')
    names = {r['id']: r['name'] for r in q.execute('SELECT id, name FROM suras')}
    want = {(s, x) for (s, a) in result_keys for x in range(a, aya_to.get((s, a), a) + 1)}
    texts = {(r['sura_id'], r['aya_num']): r['text_tashkeel']
             for r in q.execute('SELECT sura_id, aya_num, text_tashkeel FROM ayas') if (r['sura_id'], r['aya_num']) in want}
    q.close()

    results, per_src, type_cnt, sura_stats = [], Counter(), Counter(), {}
    for s, a in result_keys:
        ids, chips, n_img = [], [], 0
        for src in show:
            for r in match[(s, a)][src]:
                ids.append(r['id'])
                chips.append([src, r['main_type'], r['hukm']])
                per_src[src] += 1
                type_cnt[(src, r['main_type'])] += 1
                n_img += 1
        a_end = aya_to.get((s, a), a)
        results.append({'sura': s, 'sura_name': names.get(s, str(s)), 'aya': a, 'aya_to': a_end,
                        'texts': [texts.get((s, x), '') for x in range(a, a_end + 1)], 'ids': ids, 'chips': chips})
        st = sura_stats.setdefault(s, {'sura_id': s, 'name': names.get(s, str(s)), 'occurrences': 0, 'ayahs': 0})
        st['occurrences'] += n_img
        st['ayahs'] += 1

    order = {k: i for i, k in enumerate(keys)}
    return {
        'results': results,
        'ayahs': len(results),
        'images': sum(per_src.values()),
        'per_source': [[name[k], per_src[k]] for k in show if per_src.get(k)],
        'by_type': [[name[s], t, n] for (s, t), n in sorted(type_cnt.items(), key=lambda x: (order[x[0][0]], -x[1]))],
        'top_suras': sorted(sura_stats.values(), key=lambda x: (-x['occurrences'], -x['ayahs'], x['sura_id'])),
        'shown_sources': show,
        'label': describe(f, srcs, mode),
        'coverage_note': note,
    }


def describe(f, srcs, mode):
    t = f.get('type', 'ALL')
    parts = [TYPE_LABELS.get(t, t), 'المصدر: ' + _mode_label(mode, srcs)]
    if f.get('sura') not in (None, '', 'all'):
        parts.append('سورة رقم ' + str(f['sura']))
    if f.get('period') == 'meccan':
        parts.append('المكي')
    if f.get('period') == 'medinan':
        parts.append('المدني')
    if f.get('function', 'all') != 'all':
        parts.append('الوظيفة: ' + f['function'])
    if f.get('ibn', 'all') != 'all':
        parts.append('ابن المنيّر: ' + f['ibn'])
    if f.get('stance', 'all') != 'all':
        parts.append('الموقف من الكشاف: ' + f['stance'])
    if f.get('text'):
        parts.append('النص: «' + f['text'] + '»')
    if f.get('include_ihtimal'):
        parts.append('مع الاحتمالات')
    return ' | '.join(parts)


def aya_details(sura, aya):
    """كل صفوف الآية من كل المفسّرين، بترتيب أعمدة Excel، ومواضع «خارج العدّ» فيها."""
    c = _conn()
    srcs = _sources(c)
    order = {s['key']: i for i, s in enumerate(srcs)}
    name = {s['key']: s['name'] for s in srcs}
    rows = c.execute('SELECT id, source, main_type, hukm, raw_json, row_no FROM images WHERE sura_id=? AND aya_from=?',
                     (int(sura), int(aya))).fetchall()
    out = c.execute('SELECT source, kind, raw_json FROM outside WHERE sura_id=? AND aya_from=? ORDER BY source, row_no',
                    (int(sura), int(aya))).fetchall()
    c.close()
    rows = sorted(rows, key=lambda r: (order.get(r['source'], 99), r['row_no'] or 0))
    return {
        'rows': [{'id': r['id'], 'source': r['source'], 'source_name': name.get(r['source'], r['source']),
                  'main_type': r['main_type'], 'hukm': r['hukm'], 'fields': json.loads(r['raw_json'])} for r in rows],
        'outside': [{'source': r['source'], 'source_name': name.get(r['source'], r['source']), 'kind': r['kind'],
                     'fields': json.loads(r['raw_json'])} for r in sorted(out, key=lambda r: order.get(r['source'], 99))],
    }


def outside_list(f, rev_order):
    """مواضع «خارج العدّ» بحسب النوع والمفسّر والنطاق والنص."""
    c = _conn()
    srcs = _sources(c)
    name = {s['key']: s['name'] for s in srcs}
    rows = c.execute('SELECT source, kind, sura_id, sura_name, aya_raw, lafz, text, juz_page, page_id FROM outside '
                     'ORDER BY sura_id, aya_from, row_no').fetchall()
    c.close()
    text_n = ' '.join(_norm(f.get('text', '')).split())
    out = []
    for r in rows:
        if f.get('kind', 'all') != 'all' and r['kind'] != f['kind']:
            continue
        if f.get('osource', 'all') != 'all' and r['source'] != f['osource']:
            continue
        if not _sura_ok(r['sura_id'], f, rev_order):
            continue
        if text_n and text_n not in _norm(f"{r['lafz']} {r['text']}"):
            continue
        d = dict(r)
        d['source_name'] = name.get(r['source'], r['source'])
        out.append(d)
    return out


# ---------------------------------------------------------------------------- تصدير Word
MUSHAF_BINS = [(1, 11, 'الفاتحة-هود'), (12, 22, 'يوسف-الحج'), (23, 34, 'المؤمنون-سبأ'), (35, 45, 'فاطر-الجاثية'),
               (46, 57, 'الأحقاف-الحديد'), (58, 68, 'المجادلة-القلم'), (69, 79, 'الحاقة-النازعات'), (80, 91, 'عبس-الشمس'),
               (92, 102, 'الليل-التكاثر'), (103, 114, 'العصر-الناس')]
REV_BINS = [(1, 11, 'العلق-الضحى'), (12, 22, 'الشرح-الإخلاص'), (23, 34, 'النجم-ق'), (35, 45, 'البلد-طه'),
            (46, 57, 'الواقعة-لقمان'), (58, 68, 'سبأ-الغاشية'), (69, 79, 'الكهف-المعارج'), (80, 91, 'النبأ-الممتحنة'),
            (92, 102, 'النساء-النور'), (103, 114, 'الحج-النصر')]


def _bin_counts(data, rev_order, kind):
    """عدد الصور في كل قطاع لكل مفسّر معروض (كالرسم في التبويب)."""
    bins = REV_BINS if kind == 'rev' else MUSHAF_BINS
    counts = {k: [0] * len(bins) for k in data['shown_sources']}
    for x in data['results']:
        pos = rev_order.get(x['sura'], 1) if kind == 'rev' else x['sura']
        b = next((i for i, (a, z, _) in enumerate(bins) if a <= pos <= z), None)
        for ch in x['chips']:
            if b is not None and ch[0] in counts:
                counts[ch[0]][b] += 1
    return [lab for _, _, lab in bins], counts


def create_balagha_docx(f, rev_order, charts=None):
    """تقرير Word: البحث، ثم رسما المصحف والنزول وجدولاهما، ثم الأنواع وأكثر السور ورودًا، ثم الآيات."""
    import base64
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Inches

    charts = charts or {}
    data = search_balagha(f, rev_order)
    GREEN, GREY = RGBColor(27, 94, 32), RGBColor(110, 110, 110)
    PALETTE = {'saboni': RGBColor(13, 71, 161), 'zamakhshari': RGBColor(183, 28, 28), 'ibnashur': RGBColor(46, 125, 50)}
    RLM = '‏'
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

    def run(p, text, size=12, bold=False, color=None, font=None):
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
        szCs = OxmlElement('w:szCs')
        szCs.set(qn('w:val'), str(int(size * 2)))
        rPr.append(szCs)

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

    para('الباحث في القرآن الكريم — البحث البلاغي', 16, True, GREEN)
    para('البحث: ' + data['label'], 12)
    if data['coverage_note']:
        para(data['coverage_note'], 11, False, GREY)
    para(f"النتائج: {data['ayahs']} آية، و{data['images']} صورة"
         + (' (' + '، '.join(f'{k}: {v}' for k, v in data['per_source']) + ')' if data['per_source'] else ''), 12, True)
    para()

    c = _conn()
    name = {s['key']: s['name'] for s in _sources(c)}
    c.close()
    shown_names = [name.get(k, k) for k in data['shown_sources']]

    # ---- الرسمان وجدولا القطاعات (الجدول كما رسمه المتصفح: الخطوط والوحدة والحصر المختارة)
    for kind, title in (('juz', 'التوزيع بحسب الأجزاء'), ('mushaf', 'التوزيع بحسب ترتيب المصحف'),
                        ('rev', 'التوزيع بحسب ترتيب النزول')):
        ch = charts.get(kind)
        if kind == 'juz' and not ch:
            continue
        para(title, 14, True, GREEN)
        if isinstance(ch, dict) and ch.get('headers'):
            picture(ch.get('img'))
            if ch.get('unit'):
                para('الوحدة: ' + ch['unit'], 10, False, GREY)
            table(ch['headers'], ch.get('rows') or [])
            if ch.get('note'):
                para(ch['note'], 10, False, GREY)
        else:
            picture(ch)
            labels, counts = _bin_counts(data, rev_order, kind)
            rows = [[lab] + [counts[k][i] for k in data['shown_sources']] for i, lab in enumerate(labels)]
            rows.append(['المجموع'] + [sum(counts[k]) for k in data['shown_sources']])
            table(['القطاع'] + shown_names, rows)

    # ---- الأنواع
    if data['by_type']:
        para('الأنواع', 14, True, GREEN)
        tot = Counter()
        for src, _, n in data['by_type']:
            tot[src] += n
        table(['المصدر', 'النوع', 'الصور', 'النسبة'],
              [[src, t, n, f"{100 * n / tot[src]:.1f}%"] for src, t, n in data['by_type']])

    # ---- أكثر السور ورودًا (كل السور)
    if data['top_suras']:
        para('أكثر السور ورودًا', 14, True, GREEN)
        tot_occ = sum(x['occurrences'] for x in data['top_suras']) or 1
        table(['#', 'السورة', 'الصور', 'الآيات', 'النسبة'],
              [[i, x['name'], x['occurrences'], x['ayahs'], f"{100 * x['occurrences'] / tot_occ:.1f}%"]
               for i, x in enumerate(data['top_suras'], 1)])

    # ---- الآيات
    para('الآيات', 14, True, GREEN)
    ids_all = {i for x in data['results'] for i in x['ids']}
    c = _conn()
    raw = {r['id']: (r['source'], json.loads(r['raw_json'])) for r in c.execute('SELECT id, source, raw_json FROM images')
           if r['id'] in ids_all}
    c.close()
    for i, x in enumerate(data['results'], 1):
        p = para()
        run(p, f'{i}. ﴿ ' + ' ۝ '.join(x['texts']) + ' ﴾ ', 16, False, None, 'Traditional Arabic')
        rng = f"{x['aya']}-{x['aya_to']}" if x['aya_to'] > x['aya'] else str(x['aya'])
        run(p, f"[{x['sura_name']}: {rng}]", 11, True, GREY)
        for rid in x['ids']:
            src, fields = raw[rid]
            para('عند ' + name.get(src, src) + ':', 11, True, PALETTE.get(src, GREY))
            for h, v in fields:
                if v is None or h in ('الرقم', 'رقم السورة', 'السورة', 'الآية'):
                    continue
                p2 = para()
                run(p2, f'{h}: ', 10, True)
                run(p2, v, 10)
        para()
    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream
