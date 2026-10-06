# -*- coding: utf-8 -*-
"""
مقارنة عدد مواضع كل جذر بين التبويب 1 (سجلات root_words) والتبويب 2 (البحث بالجذر).
للقراءة فقط: لا يعدّل شيئًا.
"""
from grammar_engine import (
    get_db_connection, adjust_word_no_for_masaq, strip_diacritics,
    pick_stem_for_root, search_grammar, UNSTABLE_ROOTS,
)

WEAK_LETTERS = ' اأإآىءؤئوية'


def _fail_reason(segs, strong, word_stem_holder):
    """يعيد (نجح؟، السبب، الكلمة) لموضع في MASAQ يُحاكي مسار search_grammar."""
    if not segs:
        return False, 'لا توجد كلمة في MASAQ', ''
    stem = pick_stem_for_root(segs, strong)
    if stem is None:
        return False, 'لا جذع محدد للكلمة', segs[0]['Word']
    word_clean = strip_diacritics(stem['Word'])
    if strong and not strong.issubset(set(word_clean)):
        return False, 'أسقطتها بصمة الجذر', stem['Word']
    return True, '', stem['Word']


def run_root_count_comparison(verify_real=True, max_real=40):
    q = get_db_connection('quran.db')
    m = get_db_connection('MASAQ.db')

    sura_names = {r['id']: r['name'] for r in q.execute("SELECT id, name FROM suras")}

    # MASAQ مرة واحدة
    grouped = {}
    for r in m.execute("""SELECT Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood
                          FROM MASAQ ORDER BY Sura_No, Verse_No, Word_No"""):
        key = (int(r['Sura_No']), int(r['Verse_No']), int(r['Word_No']))
        grouped.setdefault(key, []).append(dict(r))

    # سجلات الجذور مجمّعة بالجذر المنظَّف (كما يفعل البحث)
    roots = {}
    for r in q.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral AS root
                          FROM root_words rw JOIN roots r ON rw.root_id = r.id"""):
        try:
            clean = r['root'].replace(' ', '')
            roots.setdefault(clean, []).append(
                (int(r['sura_id']), int(r['aya_num']), int(r['word_location'].split(':')[2])))
        except Exception:
            pass

    mismatches = []
    for root, recs in roots.items():
        strong = set(c for c in root if c not in WEAK_LETTERS)
        if root in UNSTABLE_ROOTS:
            strong = set()

        valid = {}   # موضع MASAQ بعد التعديل -> الأرقام الأصلية في quran.db
        details = []
        for s, v, w in recs:
            aw = adjust_word_no_for_masaq(s, v, w)
            if aw is None:
                details.append({'sura': sura_names.get(s, str(s)), 'verse': v, 'orig': w, 'adj': None,
                                'reason': 'None مقصود في التحويلات', 'word': ''})
                continue
            valid.setdefault((s, v, aw), []).append(w)

        found = 0
        for (s, v, aw), origs in valid.items():
            ok, reason, word = _fail_reason(grouped.get((s, v, aw)), strong, None)
            if ok:
                found += 1
                for extra in origs[1:]:
                    details.append({'sura': sura_names.get(s, str(s)), 'verse': v, 'orig': extra, 'adj': aw,
                                    'reason': 'سجلان على كلمة MASAQ واحدة', 'word': word})
            else:
                for o in origs:
                    details.append({'sura': sura_names.get(s, str(s)), 'verse': v, 'orig': o, 'adj': aw,
                                    'reason': reason, 'word': word})

        raw = len(recs)
        if found != raw:
            mismatches.append({'root': root, 'tab1': raw, 'tab2': found,
                               'diff': raw - found, 'details': details, 'real_count': None})

    mismatches.sort(key=lambda x: (-x['diff'], x['root']))
    q.close()
    m.close()

    # تأكيد بالبحث الفعلي للجذور المختلفة (سقف لتجنب البطء)
    if verify_real:
        for item in mismatches[:max_real]:
            try:
                res = search_grammar({'search_text': item['root'], 'search_type': 'root'})
                item['real_count'] = res['count']
            except Exception:
                item['real_count'] = None

    return {
        'summary': {'roots_checked': len(roots), 'mismatched': len(mismatches),
                    'verified_real': min(len(mismatches), max_real) if verify_real else 0},
        'issues': mismatches,
    }


def export_root_count_excel(result):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "مقارنة أعداد الجذور"
    ws.append(["الجذر", "التبويب 1", "التبويب 2", "الفرق", "السورة", "الآية",
               "رقم الكلمة (quran.db)", "بعد التعديل", "كلمة MASAQ", "السبب"])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i in result['issues']:
        for d in i['details']:
            ws.append([i['root'], i['tab1'], i['tab2'], i['diff'], d['sura'], d['verse'],
                       d['orig'], d['adj'] if d['adj'] is not None else '', d['word'], d['reason']])

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)
    return wb