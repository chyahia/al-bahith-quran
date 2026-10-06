# -*- coding: utf-8 -*-
"""
فحص وسم الجذع للكلمات المنسوبة لجذور.
كل كلمة تنسب لها root_words جذرًا يُفترض أن جذعها اسم أو فعل؛ فإن كان وسم الجذع
ضميرًا أو حرف جر أو حرف عطف فهي مشتبهة (مثل: هَمَّ وُسمت PRON ومَنَّ وُسمت PREP).
للقراءة فقط: لا يعدّل شيئًا.
"""
from grammar_engine import (
    get_db_connection, adjust_word_no_for_masaq, strip_diacritics,
    pick_stem_for_root, UNSTABLE_ROOTS,
)

WEAK_LETTERS = ' اأإآىءؤئوية'

SUSPECT_EXACT = {'PREP', 'CONJ'}


def _is_suspect_tag(tag):
    t = str(tag).strip().upper()
    return t in SUSPECT_EXACT or 'PRON' in t


# أزواج (الجذر، الوسم) راجعها إنسان وقرر أنها سليمة: أدوات استفهام وموصولات لها جذور في القاعدة.
# أضف هنا فقط بعد مراجعة فردية حقيقية.
KNOWN_LEGIT_PAIRS = {
    ('كيف', 'INTERROG_PRON'),
    ('اني', 'INTERROG_PRON'),
    ('ايي', 'REL_PRON'),
    ('ايي', 'INTERROG_PRON'),   # لِأَيِّ (المرسلات 12): أيّ استفهامية
    ('ايي', 'PREP'),            # بِأَيِّ (لقمان 34): الجذع المختار هو الباء لا أيّ، وليس خطأ وسم
}

CATEGORY_LABELS = {
    'NEW': 'مجموعات جديدة (تحتاج مراجعة)',
    'KNOWN': 'مجموعات معتمدة سليمة',
}


def run_root_tag_check():
    q = get_db_connection('quran.db')
    m = get_db_connection('MASAQ.db')

    sura_names = {r['id']: r['name'] for r in q.execute("SELECT id, name FROM suras")}

    grouped = {}
    for r in m.execute("""SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word,
                                 Morph_Tag, Syntactic_Role, Case_Mood
                          FROM MASAQ ORDER BY Sura_No, Verse_No, Word_No, Segment_No"""):
        key = (int(r['Sura_No']), int(r['Verse_No']), int(r['Word_No']))
        grouped.setdefault(key, []).append(dict(r))

    rows = q.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral AS root
                        FROM root_words rw JOIN roots r ON rw.root_id = r.id""").fetchall()

    groups = {}   # (root, tag) -> قائمة المواضع
    seen = set()  # لتجنب عد الموضع نفسه مرتين لنفس الجذر
    checked = 0
    for r in rows:
        s, v = int(r['sura_id']), int(r['aya_num'])
        root = r['root'].replace(' ', '')
        w = adjust_word_no_for_masaq(s, v, int(r['word_location'].split(':')[2]))
        if w is None:
            continue
        segs = grouped.get((s, v, w))
        if not segs or (root, s, v, w) in seen:
            continue
        seen.add((root, s, v, w))
        checked += 1

        strong = set(c for c in root if c not in WEAK_LETTERS)
        if root in UNSTABLE_ROOTS:
            strong = set()
        stem = pick_stem_for_root(segs, strong)
        if stem is None or not _is_suspect_tag(stem['Morph_Tag']):
            continue

        tag = str(stem['Morph_Tag']).strip()
        groups.setdefault((root, tag), []).append({
            'sura_no': s, 'sura_name': sura_names.get(s, str(s)), 'verse_no': v, 'word_no': w,
            'word': stem['Word'], 'id': stem['ID'], 'segment_no': stem['Segment_No'],
        })

    q.close()
    m.close()

    issues = []
    for (root, tag), items in groups.items():
        issues.append({
            'category': 'KNOWN' if (root, tag) in KNOWN_LEGIT_PAIRS else 'NEW',
            'root': root, 'tag': tag, 'count': len(items), 'items': items,
        })
    # الجديدة أولًا، والأقل عددًا أولًا (الأرجح أن تكون أخطاء وسم)
    issues.sort(key=lambda x: (x['category'] != 'NEW', x['count'], x['root']))

    return {
        'summary': {'checked': checked,
                    'new_groups': sum(1 for i in issues if i['category'] == 'NEW'),
                    'known_groups': sum(1 for i in issues if i['category'] == 'KNOWN'),
                    'new_words': sum(i['count'] for i in issues if i['category'] == 'NEW')},
        'labels': CATEGORY_LABELS,
        'issues': issues,
    }


def export_root_tag_excel(result):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "فحص وسم الجذوع"
    ws.append(["الفئة", "الجذر", "الوسم", "عدد المجموعة", "السورة", "الآية",
               "رقم الكلمة", "الكلمة", "ID", "Segment_No"])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for g in result['issues']:
        for it in g['items']:
            ws.append([result['labels'][g['category']], g['root'], g['tag'], g['count'],
                       it['sura_name'], it['verse_no'], it['word_no'], it['word'],
                       it['id'], it['segment_no']])

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)
    return wb