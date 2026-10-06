# -*- coding: utf-8 -*-
"""
مقارنة نوع الكلمة بين التبويبين لكل موضع جذر في root_words.
  - التبويب 1: تصنيف الكلمة كما في لوحة «الأسماء / الأفعال» (classify_word_kind).
  - التبويب 2: تصنيف الجذع الذي يختاره البحث بالجذر (pick_stem_for_root) بالمصنِّف نفسه.
كلاهما بعد مواءمة الترقيم (adjust_word_no_for_masaq) وتقسيم الكلمة المزدوجة
(split_shared_word_segments)، تمامًا كما في get_grammar_stats و search_grammar.
للقراءة فقط: لا يعدّل شيئًا. معيار النجاح: صفر فروق جديدة في النوع.
"""
from grammar_engine import (
    get_db_connection, adjust_word_no_for_masaq, split_shared_word_segments,
    pick_stem_for_root, classify_masaq_segment, classify_word_kind, UNSTABLE_ROOTS,
    NOMINAL_FUNCTION_LABEL,
)

WEAK_LETTERS = ' اأإآىءؤئوية'

# (السورة، الآية، رقم الكلمة في root_words، الجذر): مواضع راجعها إنسان وقرر قبول الفرق فيها.
# أضف هنا فقط بعد مراجعة فردية حقيقية.
KNOWN_EXCEPTIONS = {
}

KIND_AR = {'noun': 'اسم', 'verb': 'فعل', None: 'لا يُصنَّف'}

CATEGORY_LABELS = {
    'NEW': 'فرق في النوع (اسم/فعل) — يحتاج مراجعة',
    'KNOWN': 'فرق في النوع راجعناه وقُبل',
    'DETAIL': 'النوع متفق والتفصيل مختلف (الحالة أو الزمن) — للاطلاع',
    'NOMINAL': 'اسم أداة في التبويب 1، وجذعه أداة في التبويب 2 (كيف، أنّى، أيّ، كُلَّمَا) — متفق عليه، للاطلاع',
    'NONE': 'غير مصنَّفة في التبويبين معًا (حرف أو وسم مفقود) — للاطلاع',
}


def run_word_kind_check():
    q = get_db_connection('quran.db')
    m = get_db_connection('MASAQ.db')
    sura_names = {r['id']: r['name'] for r in q.execute("SELECT id, name FROM suras")}

    grouped = {}
    for r in m.execute("""SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag,
                                 Syntactic_Role, Case_Mood
                          FROM MASAQ ORDER BY Sura_No, Verse_No, Word_No, Segment_No"""):
        grouped.setdefault((int(r['Sura_No']), int(r['Verse_No']), int(r['Word_No'])), []).append(dict(r))

    rows = q.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral AS root
                        FROM root_words rw JOIN roots r ON rw.root_id = r.id""").fetchall()

    checked = agree = both_none = 0
    issues = []
    seen = set()
    for r in rows:
        try:
            s, v = int(r['sura_id']), int(r['aya_num'])
            w = int(r['word_location'].split(':')[2])
        except Exception:
            continue
        root = r['root'].replace(' ', '')
        if (root, s, v, w) in seen:
            continue
        seen.add((root, s, v, w))

        mw = adjust_word_no_for_masaq(s, v, w)
        segs = grouped.get((s, v, mw)) if mw is not None else None
        if not segs:
            continue   # المفقود في MASAQ تكشفه أداة «ربط الجذور»
        checked += 1

        own = split_shared_word_segments(s, v, w, mw, segs, word_of=lambda x: x['Word'])
        t1 = classify_word_kind([(x['Morph_Tag'], x['Case_Mood']) for x in own])

        strong = set() if root in UNSTABLE_ROOTS else set(c for c in root if c not in WEAK_LETTERS)
        stem = pick_stem_for_root(own, strong)
        t2 = classify_masaq_segment(stem['Morph_Tag'], stem['Case_Mood']) if stem else None

        k1, k2 = (t1[0] if t1 else None), (t2[0] if t2 else None)
        if k1 == k2 and (t1[1] if t1 else None) == (t2[1] if t2 else None):
            agree += 1
            if k1 is None:
                both_none += 1
                issues.append({
                    'category': 'NONE', 'root': root,
                    'sura_no': s, 'sura_name': sura_names.get(s, str(s)), 'verse_no': v,
                    'word_no': w, 'masaq_word_no': mw,
                    'word': own[0]['Word'] if own else '',
                    'tags': ' + '.join(str(x['Morph_Tag']) for x in own),
                    'tab1': KIND_AR[None],
                    'tab2': KIND_AR[None] + (f" [{stem['Morph_Tag']}]" if stem else ''),
                })
            continue

        if k1 == 'noun' and t1[1] == NOMINAL_FUNCTION_LABEL and k2 is None:
            # التبويب 2 لا يصنّف اسمًا/فعلًا، ويعرض جذع الأداة بوسمه («يا» أو «أيّ»...)؛
            # وجعل «أيّ» جذعًا فيه يتطلب تغيير معاملة الضمائر (قرار 9.2)، فلم يُفعل.
            category = 'NOMINAL'
        elif k1 != k2:
            category = 'KNOWN' if (s, v, w, root) in KNOWN_EXCEPTIONS else 'NEW'
        else:
            category = 'DETAIL'
        issues.append({
            'category': category, 'root': root,
            'sura_no': s, 'sura_name': sura_names.get(s, str(s)), 'verse_no': v,
            'word_no': w, 'masaq_word_no': mw,
            'word': own[0]['Word'] if own else '',
            'tags': ' + '.join(str(x['Morph_Tag']) for x in own),
            'tab1': t1[1] if t1 else KIND_AR[None],
            'tab2': (t2[1] if t2 else KIND_AR[None]) + (f" [{stem['Morph_Tag']}]" if stem else ''),
        })

    q.close()
    m.close()
    order = {'NEW': 0, 'KNOWN': 1, 'DETAIL': 2, 'NOMINAL': 3, 'NONE': 4}
    issues.sort(key=lambda x: (order[x['category']], x['sura_no'], x['verse_no'], x['word_no']))
    return {
        'summary': {
            'checked': checked, 'agree': agree, 'both_unclassified': both_none,
            'new': sum(1 for i in issues if i['category'] == 'NEW'),
            'known': sum(1 for i in issues if i['category'] == 'KNOWN'),
            'detail': sum(1 for i in issues if i['category'] == 'DETAIL'),
            'nominal': sum(1 for i in issues if i['category'] == 'NOMINAL'),
            # both_unclassified: مواضع NONE (مدرجة في issues للاطلاع، ولا تُعدّ فروقًا)
        },
        'labels': CATEGORY_LABELS,
        'issues': issues,
    }


def export_word_kind_excel(result):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "مقارنة نوع الكلمة"
    ws.append(["الفئة", "الجذر", "السورة", "الآية", "رقم الكلمة (quran.db)", "رقم MASAQ",
               "الكلمة", "تسلسل الأوسمة", "التبويب 1", "التبويب 2 [وسم الجذع]"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i in result['issues']:
        ws.append([result['labels'][i['category']], i['root'], i['sura_name'], i['verse_no'],
                   i['word_no'], i['masaq_word_no'], i['word'], i['tags'], i['tab1'], i['tab2']])
    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 45)
    return wb
