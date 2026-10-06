# -*- coding: utf-8 -*-
"""
قبل اعتماد grammar_engine.py الجديد: أي كلمات يتغير جذعها المختار في التبويب 2؟
القديم = pick_stem_segment المعتمد حاليًا (الخطوة 2).
الجديد = grammar_engine.pick_stem_segment المقترح (الخطوة 3: موقع وظيفة الحرف لا يُعدّ موقعًا إعرابيًا).
الجزء 1: البحث العادي على كل كلمات MASAQ. الجزء 2: البحث بالجذر على كل مواضع root_words.
قراءة فقط. الاستعمال: python check_stem_change.py  (بجانب القاعدتين و grammar_engine.py الجديد)
"""
from collections import Counter
from grammar_engine import (get_db_connection, is_affix_tag, _fallback_stem, VERB_CORE_TAGS,
                            pick_stem_segment, strip_diacritics, adjust_word_no_for_masaq,
                            split_shared_word_segments, UNSTABLE_ROOTS,
                            classify_masaq_segment)

WEAK = ' اأإآىءؤئوية'


def old_pick(segments):
    """النسخة المعتمدة حاليًا (الخطوة 2): NON_INFLECT لا يُعدّ موقعًا، والاسم/الفعل يُقدَّم حين لا موقع."""
    for seg in segments:
        if str(seg['Morph_Tag']).strip().upper() in VERB_CORE_TAGS:
            return seg
    best_content = best_other = best_no_role = None
    for seg in segments:
        if is_affix_tag(seg['Morph_Tag']):
            continue
        role = str(seg['Syntactic_Role'] or '').strip().upper()
        if role == 'NON_INFLECT':
            if best_no_role is None:
                best_no_role = seg
            continue
        if role and role != 'NONE':
            return seg
        if classify_masaq_segment(seg['Morph_Tag'], seg['Case_Mood']) is not None:
            if best_content is None:
                best_content = seg
        elif best_other is None:
            best_other = seg
    for candidate in (best_content, best_other, best_no_role):
        if candidate is not None:
            return candidate
    return _fallback_stem(segments)


def restrict(segments, strong):
    if strong and len({x['Word'] for x in segments}) > 1:
        own = [x for x in segments if strong.issubset(set(strip_diacritics(x['Word'] or '')))]
        if own:
            return own
    return segments


def desc(x):
    return f"{x['Morph_Tag']}/{x['Syntactic_Role']}" if x else 'None'


m = get_db_connection('MASAQ.db')
grouped = {}
for r in m.execute("""SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag,
                             Syntactic_Role, Case_Mood FROM MASAQ
                      ORDER BY Sura_No, Verse_No, Word_No, Segment_No"""):
    grouped.setdefault((r['Sura_No'], r['Verse_No'], r['Word_No']), []).append(dict(r))
m.close()

rows_out = []
p1 = Counter()
for key, segs in grouped.items():
    a, b = old_pick(segs), pick_stem_segment(segs)
    if a is not b:
        p1[(desc(a), desc(b))] += 1
        rows_out.append(['بحث عادي', '', *key, segs[0]['Word'],
                         " + ".join(f"{x['Morph_Tag']}/{x['Syntactic_Role']}" for x in segs), desc(a), desc(b)])
print(f"الجزء 1 (البحث العادي): كلمات فُحصت {len(grouped)} | يتغير جذعها {sum(p1.values())}")
for (o, n), c in p1.most_common(40):
    print(f"   {o} -> {n}: {c}")

q = get_db_connection('quran.db')
p2 = Counter()
checked = 0
for r in q.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral AS root
                      FROM root_words rw JOIN roots r ON rw.root_id = r.id"""):
    s, v = int(r['sura_id']), int(r['aya_num'])
    w = int(r['word_location'].split(':')[2])
    root = r['root'].replace(' ', '')
    mw = adjust_word_no_for_masaq(s, v, w)
    segs = grouped.get((s, v, mw)) if mw is not None else None
    if not segs:
        continue
    checked += 1
    strong = set() if root in UNSTABLE_ROOTS else set(c for c in root if c not in WEAK)
    own = restrict(split_shared_word_segments(s, v, w, mw, segs, word_of=lambda x: x['Word']), strong)
    a, b = old_pick(own), pick_stem_segment(own)
    if a is not b:
        p2[(desc(a), desc(b))] += 1
        rows_out.append(['بحث بالجذر', root, s, v, w, segs[0]['Word'],
                         " + ".join(f"{x['Morph_Tag']}/{x['Syntactic_Role']}" for x in own), desc(a), desc(b)])
q.close()
print(f"\nالجزء 2 (البحث بالجذر): مواضع فُحصت {checked} | يتغير جذعها {sum(p2.values())}")
for (o, n), c in p2.most_common(40):
    print(f"   {o} -> {n}: {c}")

try:
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "تغير الجذع"
    ws.append(["نوع البحث", "الجذر", "السورة", "الآية", "الكلمة", "النص",
               "تسلسل الأوسمة/المواقع", "الجذع القديم", "الجذع الجديد"])
    for row in rows_out:
        ws.append(row)
    wb.save("تغير_الجذع.xlsx")
    print("\nحُفظ الملف: تغير_الجذع.xlsx")
except ImportError:
    pass
