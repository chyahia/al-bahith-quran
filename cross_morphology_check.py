# -*- coding: utf-8 -*-
"""
مقارنة مستقلة بين MASAQ.db وجدول morphology في quran.db: هل في الكلمة فعل؟
للقراءة فقط: لا يعدّل شيئًا. الجدولان قد يخطئان، فالنتائج مرشحات للمراجعة لا أحكام.
"""
from grammar_engine import get_db_connection, adjust_word_no_for_masaq, VERB_TAGS  # مرجع واحد لأوسمة الفعل

# (النوع، السورة، الآية، رقم الكلمة في MASAQ): مواضع راجعها إنسان وقرر تركها.
# A = فعل في morphology بلا وسم فعل في MASAQ | B = وسم فعل في MASAQ بلا فعل في morphology.
# أضف هنا فقط بعد مراجعة فردية حقيقية.
KNOWN_KEYS = {
    ('A', 27, 39, 6), ('A', 27, 40, 8), ('A', 44, 19, 7),    # آتِيكَ/آتِيكُمْ: خلاف نحوي (اسم فاعل أو مضارع)
    ('A', 16, 92, 18), ('A', 38, 3, 8),                       # أَرْبَى (أفعل تفضيل)، وَلَاتَ
    ('A', 2, 181, 3), ('A', 2, 181, 8), ('A', 8, 6, 4), ('A', 8, 6, 6), ('A', 8, 6, 10), ('A', 13, 37, 8),
    ('B', 2, 181, 4), ('B', 2, 181, 9), ('B', 8, 6, 5), ('B', 8, 6, 7), ('B', 13, 37, 9),
                                                              # اختلاف مواءمة الأرقام في آيات الدمج
    ('B', 10, 28, 8), ('B', 12, 31, 23), ('B', 12, 51, 10),  # مَكَانَكُمْ، حَاشَ ×2: خلاف نحوي
    ('B', 53, 48, 4),                                         # وَأَقْنَى: الخطأ في morphology نفسه
}
KNOWN_TAG_MARKERS = ('NOUN_VERB_LIKE',)   # اصطلاح مقصود في MASAQ (هاتوا، تعالوا، هلمّ...)

CATEGORY_LABELS = {'NEW': 'مرشحات جديدة (تحتاج مراجعة)', 'KNOWN': 'راجعناها وتُركت عمدًا'}
KIND_LABELS = {'A': 'فعل في morphology وبلا وسم فعل في MASAQ',
               'B': 'وسم فعل في MASAQ وبلا فعل في morphology'}


def run_cross_morphology():
    q = get_db_connection('quran.db')
    m = get_db_connection('MASAQ.db')
    sura_names = {r['id']: r['name'] for r in q.execute("SELECT id, name FROM suras")}

    masaq = {}
    for r in m.execute("SELECT Sura_No, Verse_No, Word_No, Word, Morph_Tag FROM MASAQ"):
        masaq.setdefault((int(r['Sura_No']), int(r['Verse_No']), int(r['Word_No'])), []).append(
            (str(r['Morph_Tag']), r['Word']))

    corp = {}
    for r in q.execute("SELECT sura_id, aya_num, word_num, tag, arabic_grammar FROM morphology ORDER BY id"):
        w = adjust_word_no_for_masaq(int(r['sura_id']), int(r['aya_num']), int(r['word_num']))
        if w is None:
            continue
        corp.setdefault((int(r['sura_id']), int(r['aya_num']), w), []).append((r['tag'], r['arabic_grammar']))

    compared = agree = 0
    issues = []
    for key, parts in corp.items():
        mw = masaq.get(key)
        if not mw:
            continue
        compared += 1
        corp_verb = any(t == 'V' for t, _ in parts)
        masaq_verb = any(t in VERB_TAGS for t, _ in mw)
        if corp_verb == masaq_verb:
            agree += 1
            continue
        kind = 'A' if corp_verb else 'B'
        tags = [t for t, _ in mw]
        known = (kind, *key) in KNOWN_KEYS or any(mk in t for t in tags for mk in KNOWN_TAG_MARKERS)
        issues.append({
            'kind': kind, 'category': 'KNOWN' if known else 'NEW',
            'sura_no': key[0], 'sura_name': sura_names.get(key[0], str(key[0])),
            'verse_no': key[1], 'word_no': key[2],
            'word': mw[0][1], 'masaq_tags': ' '.join(tags),
            'corpus_parts': ' | '.join(f"{t}: {g}" for t, g in parts),
        })

    q.close()
    m.close()
    issues.sort(key=lambda x: (x['category'] != 'NEW', x['kind'], x['sura_no'], x['verse_no'], x['word_no']))
    return {
        'summary': {'compared': compared, 'agree': agree,
                    'new': sum(1 for i in issues if i['category'] == 'NEW'),
                    'known': sum(1 for i in issues if i['category'] == 'KNOWN')},
        'labels': CATEGORY_LABELS, 'kinds': KIND_LABELS, 'issues': issues,
    }


def export_cross_morphology_excel(result):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "مقارنة morphology"
    ws.append(["الفئة", "النوع", "السورة", "الآية", "رقم الكلمة", "كلمة MASAQ", "أوسمة MASAQ", "أجزاء morphology"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i in result['issues']:
        ws.append([result['labels'][i['category']], result['kinds'][i['kind']], i['sura_name'], i['verse_no'],
                   i['word_no'], i['word'], i['masaq_tags'], i['corpus_parts']])
    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 45)
    return wb