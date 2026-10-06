# -*- coding: utf-8 -*-
"""
فحص سلامة ربط الجذور بين quran.db و MASAQ.db
يتحقق أن كل سجل في root_words تقابله في MASAQ كلمة تحمل حروف جذره الصلبة.
للقراءة فقط: لا يعدّل شيئًا.
"""
from grammar_engine import get_db_connection, adjust_word_no_for_masaq, strip_diacritics

# جذور يُعرف أن حروفها تتبدل في الكلمة (إعلال/إبدال)؛ ظهورها في الفحص ضجيج متوقع لا خطأ ترقيم.
# انتبه: إن كان سبب ظهورها "لا توجد كلمة" أو "None" فهو مشتبه حقيقي ولو كان جذرها هنا.
KNOWN_NOISE_ROOTS = {'موه', 'كون', 'ذكر', 'سطر', 'ذخر', 'شفه'}

WEAK_LETTERS = ' اأإآىءؤئوية'

CATEGORY_LABELS = {
    'REAL': 'مشتبه جديد (يحتاج مراجعة)',
    'NOISE': 'ضجيج إعلال/إبدال معروف',
}


def run_root_alignment_check():
    q = get_db_connection('quran.db')
    m = get_db_connection('MASAQ.db')

    sura_names = {r['id']: r['name'] for r in q.execute("SELECT id, name FROM suras")}

    # كل الكلمات المنسوبة لكل موضع (قد يحمل الرقم الواحد أكثر من كلمة)
    masaq = {}
    for r in m.execute("SELECT Sura_No, Verse_No, Word_No, Word FROM MASAQ ORDER BY Segment_No"):
        key = (int(r['Sura_No']), int(r['Verse_No']), int(r['Word_No']))
        masaq.setdefault(key, set()).add(strip_diacritics(r['Word']))

    rows = q.execute("""
        SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral AS root
        FROM root_words rw JOIN roots r ON rw.root_id = r.id
    """).fetchall()

    issues = []
    for r in rows:
        s, v = int(r['sura_id']), int(r['aya_num'])
        orig_w = int(r['word_location'].split(':')[2])
        root = r['root'].replace(' ', '')
        w = adjust_word_no_for_masaq(s, v, orig_w)

        problem = None
        found = ''
        if w is None:
            problem = 'None مقصود في التحويلات'
        else:
            words = masaq.get((s, v, w))
            strong = set(c for c in root if c not in WEAK_LETTERS)
            if words is None:
                problem = 'لا توجد كلمة في MASAQ'
            elif strong and not any(strong.issubset(set(x)) for x in words):
                problem = 'الكلمة لا تحمل حروف الجذر'
                found = ' | '.join(sorted(words))

        if problem is None:
            continue

        is_noise = (root in KNOWN_NOISE_ROOTS and problem == 'الكلمة لا تحمل حروف الجذر')
        issues.append({
            'category': 'NOISE' if is_noise else 'REAL',
            'sura_no': s, 'sura_name': sura_names.get(s, str(s)), 'verse_no': v,
            'orig_word_no': orig_w, 'adjusted_word_no': w,
            'root': root, 'masaq_word': found, 'problem': problem,
        })

    total = len(rows)
    q.close()
    m.close()

    # المشتبهات الجديدة أولًا
    issues.sort(key=lambda x: (x['category'] != 'REAL', x['sura_no'], x['verse_no'], x['orig_word_no']))
    summary = {
        'total_checked': total,
        'real': sum(1 for i in issues if i['category'] == 'REAL'),
        'noise': sum(1 for i in issues if i['category'] == 'NOISE'),
    }
    return {'summary': summary, 'labels': CATEGORY_LABELS, 'issues': issues}


def export_root_alignment_excel(result):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "فحص ربط الجذور"
    headers = ["الفئة", "السورة", "الآية", "رقم الكلمة (quran.db)", "رقم الكلمة بعد التعديل",
               "الجذر", "كلمة MASAQ", "المشكلة"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i in result['issues']:
        ws.append([
            result['labels'][i['category']], i['sura_name'], i['verse_no'],
            i['orig_word_no'], i['adjusted_word_no'] if i['adjusted_word_no'] is not None else '',
            i['root'], i['masaq_word'], i['problem'],
        ])

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)
    return wb