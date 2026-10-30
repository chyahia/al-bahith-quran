# -*- coding: utf-8 -*-
"""
بناء balagha.db (قاعدة «البحث البلاغي»، القسم 22 من سجل تطوير البرنامج) من ملفات Excel للمفسّرين.

المفسّرون معرَّفون في قائمة SOURCES أدناه (الصابوني، الزمخشري، ابن عاشور). ملفات Excel هي الأصل:
تعدّل فيها أو تضيف دفعات ثم تعيد تشغيل السكربت، فتُبنى القاعدة من جديد كاملة. لا يمسّ quran.db ولا MASAQ.db.

الاستعمال (بجانب quran.db وapp.py)، وكل ملف اختياري لكن يلزم واحد على الأقل:
    python build_balagha_db.py --saboni صور_الصابوني.xlsx --zamakhshari صور_الكشاف.xlsx --ibnashur صور_ابن_عاشور.xlsx
يكتب:
    balagha.db                  (تُستبدل النسخة السابقة)
    تقرير_بناء_البلاغة.xlsx     (ما يحتاج مراجعة؛ لا يمنع البناء)

ما يُقرأ من كل ملف (الأوراق والأعمدة تُعرف بأسمائها لا بمواقعها، مع تجاهل التشكيل والمسافات الزائدة):
  - ورقة «قاعدة البيانات»: الصور. الأعمدة الأساسية: رقم السورة، الآية، موضع الصورة (اللفظ)، النوع الرئيس، الحكم.
    وكل عمود آخر يُحفظ كما هو ويظهر في «تفاصيل» الآية (فإضافة عمود جديد في Excel لا تحتاج تعديل السكربت).
    أعمدة تُستعمل في الفلاتر إن وجدت: الوظيفة الحجاجية، اعتراض ابن المنيّر، الموقف من الكشاف.
  - أوراق «خارج العدّ» إن وجدت: «تأويل بلا مصطلح»، «وصف بلا مصطلح»، «نفي المجاز وردّ التأويل».
  - ورقة «إحصاء السور»: عمود «الآيات المقروءة» إن وجد (ملف لم يكتمل بعد، كابن عاشور): يحدد نطاق ما قُرئ
    من كل سورة (من الآية 1 إلى العدد المذكور). إن لم يوجد العمود فالملف يغطي القرآن كله.
    أوراق الإحصاء الأخرى لا تُقرأ (فيها معادلات)، والتبويب يحسب الإحصاء بنفسه.

التحقق (يُكتب في التقرير):
  1. اللفظ موجود في نص الآية؟ (بلا تشكيل، والهمزة محذوفة بكل صورها على الطرفين، وبالنص الإملائي والعثماني)،
     وإلا اقتُرحت آية مجاورة (±3) أو آيتان متتاليتان.
  2. السورة والآية موجودتان؟ واسم السورة مطابق؟ والنوع الرئيس من الستة؟ والحكم معروف؟
  3. صفوف خارج النطاق المقروء (عمود «الآيات المقروءة» لم يُحدَّث؟).
  4. المكي/المدني في «إحصاء السور» مقارنًا بتعريف البرنامج (ترتيب النزول ≤ 86).
"""
import argparse
import ast
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

DB_OUT = 'balagha.db'
REPORT = 'تقرير_بناء_البلاغة.xlsx'
QURAN_DB = 'quran.db'

MAIN_TYPES = ['تشبيه', 'استعارة', 'مجاز مرسل', 'مجاز عقلي', 'كناية', 'مجاز (غير محدد)']
HUKM = {'إثبات', 'احتمال', 'نقل وردّ'}

# ---------------------------------------------------------------------------- المفسّرون
# لإضافة تفسير جديد: سطر هنا، وخيار في سطر الأوامر يُنشأ تلقائيًا (--key).
SOURCES = [
    {'key': 'saboni', 'name': 'الصابوني', 'book': 'صفوة التفاسير', 'author': 'محمد علي الصابوني',
     'shamela_book_id': 8967},
    {'key': 'zamakhshari', 'name': 'الزمخشري', 'book': 'الكشاف عن حقائق غوامض التنزيل', 'author': 'جار الله الزمخشري',
     'shamela_book_id': 23627},
    {'key': 'ibnashur', 'name': 'ابن عاشور', 'book': 'التحرير والتنوير', 'author': 'محمد الطاهر ابن عاشور',
     'shamela_book_id': 9776},
]

# أوراق «خارج العدّ»: الاسم (أو بدايته) -> النوع المحفوظ
OUTSIDE_SHEETS = [
    ('تأويل بلا مصطلح', 'تأويل بلا مصطلح'),
    ('وصف بلا مصطلح', 'وصف بلا مصطلح'),
    ('نفي المجاز', 'نفي المجاز وردّ التأويل'),
]

# أعمدة «قاعدة البيانات»: (العنوان أو بدايته، الحقل، مطلوب؟)
FIELDS = [
    ('الرقم', 'row_no', False),
    ('رقم السورة', 'sura_id', True),
    ('السورة', 'sura_name', False),
    ('الآية', 'aya_raw', True),
    ('موضع الصورة', 'lafz', True),
    ('النوع الرئيس', 'main_type', True),
    ('النوع الفرعي', 'sub_type', False),
    ('الحكم', 'hukm', True),
    ('الجزء/الصفحة', 'juz_page', False),
    ('page_id', 'page_id', False),
    ('الوظيفة الحجاجية', 'function', False),
    ('اعتراض ابن المنير', 'ibn_munayyir', False),
    ('الموقف من الكشاف', 'kashaf_stance', False),
    ('ملاحظة', 'note', False),
]
OUTSIDE_FIELDS = [
    ('الرقم', 'row_no', False),
    ('رقم السورة', 'sura_id', True),
    ('السورة', 'sura_name', False),
    ('الآية', 'aya_raw', True),
    ('اللفظ', 'lafz', False),
    ('الجزء/الصفحة', 'juz_page', False),
    ('page_id', 'page_id', False),
]   # والنص: أول عمود آخر (عبارة المفسّر / ملاحظة، موقفه وعبارته...)

# ---------------------------------------------------------------------------- تطبيع
_DIAC = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')


def norm(x):
    x = _DIAC.sub('', str(x or ''))
    x = re.sub('[ٱآ]', 'ا', x)
    x = re.sub('[ءأإؤئ]', '', x)
    x = x.replace('ى', 'ي').replace('ة', 'ه')
    x = re.sub(r'[^ء-ي ]', ' ', x)
    return ' '.join(x.split())


def hnorm(h):
    """تطبيع عنوان عمود أو ورقة للمقارنة: بلا تشكيل ولا مسافات زائدة، والهمزات موحّدة."""
    h = _DIAC.sub('', str(h or '')).strip()
    h = re.sub('[أإآ]', 'ا', h)
    return ' '.join(h.split())


def lafz_segments(lafz):
    s = re.sub(r'\([^)]*\)', ' ', str(lafz or ''))
    s = re.sub(r'«[^»]*»', ' ', s)
    return [p for p in (norm(x) for x in re.split(r'\.\.\.|…|،|/', s)) if p]


def match_level(lafz, texts):
    segs = lafz_segments(lafz)
    if not segs:
        return 'فارغ'
    txt = [norm(t) for t in texts if t]
    if all(any(seg in t for t in txt) for seg in segs):
        return 'كامل'
    words = [w for seg in segs for w in seg.split()]
    tw = {w for t in txt for w in t.split()}
    hit = sum(1 for w in words if w in tw or any(w in y for y in tw))
    return 'جزئي' if hit >= max(1, len(words) / 2) else 'غير موجود'


def parse_aya(v):
    """رقم، أو مدى «32-33» (بأي شرطة)، أو «32، 33» -> (من، إلى)."""
    s = str(v).strip()
    s = re.sub(r'[–—−،,]', '-', s)
    s = s.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    nums = [int(float(x)) for x in re.findall(r'\d+(?:\.0)?', s)]
    if not nums:
        raise ValueError(s)
    return min(nums), max(nums)


def clean_val(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        return None if v in ('', 'None') else v
    return v


def to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def rev_order_from_app():
    try:
        tree = ast.parse(open('app.py', encoding='utf-8').read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'REV_ORDER_MAP' for t in node.targets):
                return ast.literal_eval(node.value)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------- قراءة Excel
def find_sheet(wb, title):
    t = hnorm(title)
    for name in wb.sheetnames:
        if hnorm(name) == t:
            return wb[name]
    for name in wb.sheetnames:
        if hnorm(name).startswith(t):
            return wb[name]
    return None


def find_col(headers, title, used=()):
    t = hnorm(title)
    hs = [hnorm(h) for h in headers]
    for i, h in enumerate(hs):
        if h == t and i not in used:
            return i
    for i, h in enumerate(hs):
        if h and h.startswith(t) and i not in used:
            return i
    return None


def read_rows(ws, fields, path, extra_text=False):
    """صفوف الورقة: الحقول المعروفة، والصف كاملًا بترتيب Excel. يعيد (الصفوف، الأخطاء البنيوية)."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    # سطر العناوين: أول سطر فيه «رقم السورة»
    hi = next((i for i, r in enumerate(rows[:10]) if r and find_col(r, 'رقم السورة') is not None), None)
    if hi is None:
        return [], [f'لا يوجد عمود «رقم السورة» في ورقة «{ws.title}» من {os.path.basename(path)}']
    headers = [clean_val(h) for h in rows[hi]]
    col, used, errors = {}, set(), []
    # «السورة» تأتي بعد «رقم السورة» لئلا تلتقطه البداية
    for title, field, required in fields:
        idx = find_col(headers, title, used)
        if field == 'sura_name' and idx is not None and hnorm(headers[idx]) != 'السورة':
            idx = next((i for i, h in enumerate(headers) if hnorm(h) == 'السورة'), None)
        if idx is None and required:
            errors.append(f'لا يوجد عمود «{title}» في ورقة «{ws.title}» من {os.path.basename(path)}')
        if idx is not None:
            used.add(idx)
        col[field] = idx
    if extra_text:
        col['text'] = next((i for i, h in enumerate(headers) if h and i not in used), None)
    if errors:
        return [], errors
    out = []
    for n, r in enumerate(rows[hi + 1:], start=hi + 2):
        if r is None or all(c is None or str(c).strip() == '' for c in r):
            continue
        rec = {f: (clean_val(r[i]) if i is not None and i < len(r) else None) for f, i in col.items()}
        if to_int(rec.get('sura_id')) is None:
            continue   # سطر مجموع أو ملاحظة
        rec['raw'] = [[headers[i], clean_val(r[i]) if i < len(r) else None]
                      for i in range(len(headers)) if headers[i]]
        rec['excel_row'] = n
        out.append(rec)
    return out, []


def read_stats_sheet(wb):
    """من «إحصاء السور»: المكي/المدني، وعدد الآيات المقروءة (إن وجد العمود)."""
    ws = find_sheet(wb, 'إحصاء السور')
    if ws is None:
        return {}, None
    rows = list(ws.iter_rows(values_only=True))
    h = rows[0]
    i_id, i_name, i_t = find_col(h, 'رقم السورة'), None, find_col(h, 'مكية/مدنية')
    i_name = next((i for i, x in enumerate(h) if hnorm(x) == 'السورة'), None)
    i_read = find_col(h, 'الآيات المقروءة')
    meccan, read = {}, ({} if i_read is not None else None)
    for r in rows[1:]:
        s = to_int(r[i_id]) if i_id is not None else None
        if s is None:
            continue
        if i_t is not None:
            meccan[s] = (r[i_name] if i_name is not None else s, r[i_t])
        if i_read is not None:
            read[s] = r[i_read]     # قد تكون None (معادلة لم تُحسب)
    return meccan, read


# ---------------------------------------------------------------------------- البناء
SCHEMA = """
CREATE TABLE sources (
    id TEXT PRIMARY KEY, ord INTEGER, name TEXT, book TEXT, author TEXT, shamela_book_id INTEGER,
    excel_file TEXT, rows INTEGER, columns_json TEXT,
    coverage_json TEXT,       -- null = القرآن كله؛ وإلا {سورة: آخر آية مقروءة}
    filters_json TEXT         -- أعمدة الفلاتر الموجودة في الملف: function / ibn_munayyir / kashaf_stance
);
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, row_no INTEGER, excel_row INTEGER,
    sura_id INTEGER NOT NULL, sura_name TEXT,
    aya_from INTEGER NOT NULL, aya_to INTEGER NOT NULL, aya_raw TEXT,
    lafz TEXT, main_type TEXT, sub_type TEXT, hukm TEXT,
    juz_page TEXT, page_id INTEGER,
    function TEXT, function_head TEXT,      -- الوظيفة الحجاجية ورأسها
    ibn_munayyir TEXT,                      -- الزمخشري
    kashaf_stance TEXT,                     -- ابن عاشور: الموقف من الكشاف
    note TEXT, lafz_match TEXT,
    raw_json TEXT                           -- الصف كاملًا بترتيب Excel
);
CREATE INDEX idx_img_aya ON images(sura_id, aya_from);
CREATE INDEX idx_img_type ON images(main_type, source);
CREATE TABLE outside (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, kind TEXT NOT NULL,   -- تأويل بلا مصطلح / وصف بلا مصطلح / نفي المجاز وردّ التأويل
    row_no INTEGER, excel_row INTEGER,
    sura_id INTEGER NOT NULL, sura_name TEXT, aya_from INTEGER, aya_to INTEGER, aya_raw TEXT,
    lafz TEXT, text TEXT, juz_page TEXT, page_id INTEGER, raw_json TEXT
);
CREATE INDEX idx_out_aya ON outside(sura_id, aya_from);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def function_head(f):
    if not f:
        return None
    return re.split(r'[(:—]', str(f))[0].strip() or None


def main():
    ap = argparse.ArgumentParser(description='بناء balagha.db من ملفات Excel للمفسّرين')
    for s in SOURCES:
        ap.add_argument('--' + s['key'], help=f"ملف Excel لصور {s['name']} ({s['book']})")
    args = ap.parse_args()
    given = [(s, getattr(args, s['key'])) for s in SOURCES if getattr(args, s['key'])]
    if not given:
        ap.error('حدّد ملفًّا واحدًا على الأقل، مثل: --zamakhshari صور_الكشاف.xlsx')
    for _, p in given:
        if not os.path.exists(p):
            sys.exit(f'خطأ: الملف غير موجود: {p}')
    if not os.path.exists(QURAN_DB):
        sys.exit('خطأ: quran.db غير موجود بجانب السكربت.')

    import openpyxl
    q = sqlite3.connect(QURAN_DB)
    sura_names = {int(i): n for i, n in q.execute('SELECT id, name FROM suras')}
    ayas = {(int(s), int(a)): (c, t, u) for s, a, c, t, u in
            q.execute('SELECT sura_id, aya_num, text_clean, text_tashkeel, text_uthmani FROM ayas')}
    aya_count = Counter(s for s, _ in ayas)
    q.close()
    rev = rev_order_from_app()

    issues, meccan_diff, coverage_rows = [], [], []
    imgs, outs, src_rows = [], [], []
    fatal = []

    for ordn, (src, path) in enumerate(given):
        key, name = src['key'], src['name']
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = find_sheet(wb, 'قاعدة البيانات')
        if ws is None:
            fatal.append(f'لا توجد ورقة «قاعدة البيانات» في {path}')
            continue
        recs, errs = read_rows(ws, FIELDS, path)
        if errs:
            fatal.extend(errs)
            continue
        meccan_sheet, read = read_stats_sheet(wb)

        # ---- النطاق المقروء
        coverage = None
        if read is not None:
            coverage = {}
            max_aya = defaultdict(int)
            for r in recs:
                s = to_int(r['sura_id'])
                try:
                    max_aya[s] = max(max_aya[s], parse_aya(r['aya_raw'])[1])
                except ValueError:
                    pass
            for s, v in read.items():
                n = to_int(v)
                if n is None:
                    if max_aya.get(s):
                        coverage[s] = max_aya[s]
                        issues.append([name, '', '', s, '', '', 'عدد «الآيات المقروءة» فارغ (معادلة لم تُحسب؟)؛ '
                                       'اعتُمد آخر آية في الصور', str(max_aya[s])])
                    continue
                if n > 0:
                    coverage[s] = min(n, aya_count.get(s, n))
            for s, m in max_aya.items():
                if m > coverage.get(s, 0):
                    issues.append([name, '', '', s, m, '', 'صور بعد آخر آية مقروءة في «إحصاء السور»: حدِّث العمود',
                                   f'المقروء {coverage.get(s, 0)}'])
                    coverage[s] = m
            for s in sorted(coverage):
                coverage_rows.append([name, s, sura_names.get(s, ''), coverage[s], aya_count.get(s)])
            # اكتملت القراءة (كل السور بكل آياتها): الملف يغطي القرآن كله، فلا حصر ولا تنبيه
            if all(coverage.get(s, 0) >= n for s, n in aya_count.items()):
                coverage = None

        filters = [f for f in ('function', 'ibn_munayyir', 'kashaf_stance') if any(r.get(f) for r in recs)]
        headers = [h for h, _ in recs[0]['raw']] if recs else []
        src_rows.append((key, ordn, src, os.path.basename(path), len(recs), headers, coverage, filters))

        for r in recs:
            def issue(problem, hint=''):
                issues.append([name, r['excel_row'], r.get('row_no'), r.get('sura_id'), r.get('aya_raw'),
                               r.get('lafz'), problem, hint])
            s = to_int(r['sura_id'])
            try:
                a0, a1 = parse_aya(r['aya_raw'])
            except (TypeError, ValueError):
                issue('رقم الآية غير صالح')
                continue
            if s not in sura_names:
                issue('سورة غير موجودة')
                continue
            if r.get('sura_name') and norm(r['sura_name']) != norm(sura_names[s]):
                issue('اسم السورة لا يطابق quran.db', sura_names[s])
            if a1 > aya_count[s] or a0 < 1:
                issue(f'الآية خارج السورة (عدد آياتها {aya_count[s]})')
                continue
            if r.get('main_type') not in MAIN_TYPES:
                issue('نوع رئيس غير معروف (لا يظهر في البحث بالنوع)', str(r.get('main_type')))
            if r.get('hukm') not in HUKM:
                issue('حكم غير معروف', str(r.get('hukm')))

            texts = [' '.join(ayas[(s, a)][i] for a in range(a0, a1 + 1)) for i in range(3)]
            level = match_level(r.get('lafz'), texts)
            if level != 'كامل':
                hint = ''
                for d in (1, -1, 2, -2, 3, -3):
                    k = (s, a0 + d)
                    if k in ayas and match_level(r.get('lafz'), ayas[k]) == 'كامل':
                        hint = f'وُجد في الآية {a0 + d}'
                        break
                if not hint:
                    for b0, b1 in ((a0, a1 + 1), (a0 - 1, a1)):
                        if (s, b0) in ayas and (s, b1) in ayas:
                            joined = [' '.join(ayas[(s, a)][i] for a in range(b0, b1 + 1)) for i in range(3)]
                            if match_level(r.get('lafz'), joined) == 'كامل':
                                hint = f'يمتد على الآيات {b0}-{b1}'
                                break
                issue(f'اللفظ {level} في نص الآية' if level != 'فارغ' else 'اللفظ فارغ', hint)

            imgs.append((key, to_int(r.get('row_no')), r['excel_row'], s, r.get('sura_name'), a0, a1,
                         str(r['aya_raw']), r.get('lafz'), r.get('main_type'), r.get('sub_type'), r.get('hukm'),
                         None if r.get('juz_page') is None else str(r['juz_page']), to_int(r.get('page_id')),
                         r.get('function'), function_head(r.get('function')), r.get('ibn_munayyir'),
                         r.get('kashaf_stance'), r.get('note'), level, json.dumps(r['raw'], ensure_ascii=False)))

        # ---- أوراق خارج العدّ
        for sheet_title, kind in OUTSIDE_SHEETS:
            ows = find_sheet(wb, sheet_title)
            if ows is None:
                continue
            orecs, oerrs = read_rows(ows, OUTSIDE_FIELDS, path, extra_text=True)
            for e in oerrs:
                issues.append([name, '', '', '', '', '', e, ''])
            for r in orecs:
                s = to_int(r['sura_id'])
                try:
                    a0, a1 = parse_aya(r['aya_raw'])
                except (TypeError, ValueError):
                    issues.append([f'{name} ({kind})', r['excel_row'], r.get('row_no'), s, r.get('aya_raw'),
                                   r.get('lafz'), 'رقم الآية غير صالح', ''])
                    continue
                outs.append((key, kind, to_int(r.get('row_no')), r['excel_row'], s, r.get('sura_name'), a0, a1,
                             str(r['aya_raw']), r.get('lafz'), r.get('text'),
                             None if r.get('juz_page') is None else str(r['juz_page']), to_int(r.get('page_id')),
                             json.dumps(r['raw'], ensure_ascii=False)))

        # ---- المكي والمدني
        if rev:
            for s, (nm, t) in sorted(meccan_sheet.items()):
                prog = 'مكية' if rev.get(s, 1) <= 86 else 'مدنية'
                if t in ('مكية', 'مدنية') and t != prog:
                    meccan_diff.append([name, s, nm, t, prog])

    if fatal:
        print('توقف البناء (لم تُمسّ balagha.db السابقة):')
        for e in fatal:
            print('   - ' + e)
        sys.exit(1)

    # ---- الكتابة (في ملف مؤقت ثم الاستبدال، فلا تُفقد القاعدة السابقة إن فشل شيء)
    tmp = DB_OUT + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    for key, ordn, src, fname, n, headers, coverage, filters in src_rows:
        db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (key, ordn, src['name'], src['book'], src['author'], src['shamela_book_id'], fname, n,
                    json.dumps(headers, ensure_ascii=False),
                    None if coverage is None else json.dumps(coverage), json.dumps(filters)))
    db.executemany('INSERT INTO images (source, row_no, excel_row, sura_id, sura_name, aya_from, aya_to, aya_raw, '
                   'lafz, main_type, sub_type, hukm, juz_page, page_id, function, function_head, ibn_munayyir, '
                   'kashaf_stance, note, lafz_match, raw_json) VALUES (' + ','.join('?' * 21) + ')', imgs)
    db.executemany('INSERT INTO outside (source, kind, row_no, excel_row, sura_id, sura_name, aya_from, aya_to, '
                   'aya_raw, lafz, text, juz_page, page_id, raw_json) VALUES (' + ','.join('?' * 14) + ')', outs)
    db.executemany('INSERT INTO meta VALUES (?,?)', [('built_at', datetime.now().isoformat(timespec='seconds'))] +
                   [(s['key'] + '_file', os.path.basename(p)) for s, p in given])
    db.commit()

    # ---- الملخص
    print('=' * 60)
    print(f'بُنيت {DB_OUT}')
    for key, _, src, fname, n, _, coverage, filters in src_rows:
        rows = db.execute('SELECT main_type, hukm, COUNT(*) FROM images WHERE source=? GROUP BY main_type, hukm',
                          (key,)).fetchall()
        tot = sum(r[2] for r in rows)
        ith = sum(r[2] for r in rows if r[1] == 'إثبات')
        ayas_n = db.execute('SELECT COUNT(DISTINCT sura_id*1000+aya_from) FROM images WHERE source=?', (key,)).fetchone()[0]
        print(f'\n{src["name"]} ({fname}): {tot} صورة ({ith} إثبات)، في {ayas_n} آية')
        by_type = Counter()
        for t, h, c in rows:
            if h == 'إثبات':
                by_type[t] += c
        print('   ' + '، '.join(f'{t}: {by_type.get(t, 0)}' for t in MAIN_TYPES))
        if coverage is not None:
            read_n = sum(coverage.values())
            print(f'   النطاق المقروء: {read_n} آية في {len(coverage)} سورة (من 6236)')
        else:
            print('   النطاق: القرآن كله')
        kinds = db.execute('SELECT kind, COUNT(*) FROM outside WHERE source=? GROUP BY kind', (key,)).fetchall()
        if kinds:
            print('   خارج العدّ: ' + '، '.join(f'{k} {c}' for k, c in kinds))
    lv = Counter(x[19] for x in imgs)
    print(f'\nالتحقق من اللفظ: كامل {lv.get("كامل", 0)}، جزئي {lv.get("جزئي", 0)}، غير موجود {lv.get("غير موجود", 0)}')
    if meccan_diff:
        print('تنبيه مكي/مدني (يُعتمد في البرنامج ترتيب النزول ≤ 86): ' +
              '، '.join(f'{d[0]}: {d[2]}' for d in meccan_diff))
    db.close()
    if os.path.exists(DB_OUT):
        os.remove(DB_OUT)
    os.replace(tmp, DB_OUT)

    # ---- التقرير
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    sheets = [
        ('للمراجعة', ['المصدر', 'سطر Excel', 'الرقم', 'السورة', 'الآية', 'اللفظ', 'المشكلة', 'اقتراح'], issues),
        ('النطاق المقروء', ['المصدر', 'رقم السورة', 'السورة', 'آخر آية مقروءة', 'عدد آيات السورة'], coverage_rows),
        ('مكي ومدني', ['المصدر', 'رقم السورة', 'السورة', 'في Excel', 'في البرنامج (النزول ≤ 86)'], meccan_diff),
    ]
    for i, (title, head, data) in enumerate(sheets):
        w = wb.active if i == 0 else wb.create_sheet()
        w.title = title
        w.sheet_view.rightToLeft = True
        w.append(head)
        for r in data:
            w.append(r)
        for c in w[1]:
            c.font = Font(bold=True)
        for col in w.columns:
            mx = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            w.column_dimensions[col[0].column_letter].width = min(mx + 3, 60)
    try:
        wb.save(REPORT)
        print(f'\n{len(issues)} صفًّا للمراجعة في «{REPORT}» (لا تمنع البناء).')
    except PermissionError:
        print(f'\nتعذّر حفظ «{REPORT}»: أغلقه في Excel ثم أعد التشغيل. (القاعدة بُنيت.)')


if __name__ == '__main__':
    main()
