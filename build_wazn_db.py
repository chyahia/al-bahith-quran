# -*- coding: utf-8 -*-
"""
بناء قاعدة بيانات الأوزان الصرفية لكلمات القرآن الكريم (quran_awzan.db)
المصدر: البيانات الصرفية للمدوّنة القرآنية العربية (Quranic Arabic Corpus v0.4)
الاستعمال:  python build_wazn_db.py quran-morphology.txt quran_awzan.db [تصحيحات_الأوزان.xlsx]
وإن وُجد ملف «تصحيحات_الأوزان.xlsx» في المجلد نفسه طُبّقت تصحيحاته تلقائيًا (انظر load_corrections).
"""
import sqlite3, sys, re, itertools
from collections import defaultdict, Counter

FATHA, DAMMA, KASRA, SUKUN, SHADDA = 'َ', 'ُ', 'ِ', 'ْ', 'ّ'
TANWEEN = 'ًٌٍ'
HARAKAT = FATHA + DAMMA + KASRA + SUKUN + SHADDA + TANWEEN
VOWELS_ONLY = FATHA + DAMMA + KASRA + TANWEEN
HAMZAS = 'أإؤئءٔ'
WEAK = 'وي'
AUGMENT = set('سألتمونيهاءىإؤئة')   # حروف الزيادة "سألتمونيها" + صور الهمزة + التاء المربوطة
FA3L = ['ف', 'ع', 'ل']
FA3LAL = ['ف', 'ع', 'ل', 'ل']

SURA_NAMES = """الفاتحة البقرة آل_عمران النساء المائدة الأنعام الأعراف الأنفال التوبة يونس هود يوسف الرعد إبراهيم الحجر النحل الإسراء الكهف مريم طه الأنبياء الحج المؤمنون النور الفرقان الشعراء النمل القصص العنكبوت الروم لقمان السجدة الأحزاب سبأ فاطر يس الصافات ص الزمر غافر فصلت الشورى الزخرف الدخان الجاثية الأحقاف محمد الفتح الحجرات ق الذاريات الطور النجم القمر الرحمن الواقعة الحديد المجادلة الحشر الممتحنة الصف الجمعة المنافقون التغابن الطلاق التحريم الملك القلم الحاقة المعارج نوح الجن المزمل المدثر القيامة الإنسان المرسلات النبأ النازعات عبس التكوير الانفطار المطففين الانشقاق البروج الطارق الأعلى الغاشية الفجر البلد الشمس الليل الضحى الشرح التين العلق القدر البينة الزلزلة العاديات القارعة التكاثر العصر الهمزة الفيل قريش الماعون الكوثر الكافرون النصر المسد الإخلاص الفلق الناس""".split()
SURA_NAMES = [s.replace('_', ' ') for s in SURA_NAMES]

VF_PAST = {  # صيغ الفعل المزيد (الثلاثي) بصيغة الماضي
    2: 'فَعَّلَ', 3: 'فَاعَلَ', 4: 'أَفْعَلَ', 5: 'تَفَعَّلَ', 6: 'تَفَاعَلَ', 7: 'انْفَعَلَ',
    8: 'افْتَعَلَ', 9: 'افْعَلَّ', 10: 'اسْتَفْعَلَ', 11: 'افْعَالَّ', 12: 'افْعَوْعَلَ'}
VF_PAST_QUAD = {1: 'فَعْلَلَ', 2: 'تَفَعْلَلَ', 3: 'افْعَنْلَلَ', 4: 'افْعَلَلَّ'}


def norm_hamza(ch):
    return 'ء' if ch in HAMZAS or ch == 'آ' else ch


# ---------------------------------------------------------------- تقطيع الرسم العثماني إلى وحدات (حرف + حركاته)
def tokenize(s, root0_hamza=False, hamza_alif_as_double=True):
    units = []  # [letter, diacritics]
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in HARAKAT:
            if units:
                units[-1][1] += ch
        elif ch == 'ـ':                           # تطويل يحمل همزة أو ألفًا
            units.append(['ـ', ''])
        elif ch == 'ٰ':                      # ألف خنجرية = ألف مد
            if units and units[-1][0] == 'ـ':
                units[-1][0] = 'ا'
            elif units and units[-1][0] == 'ى' and not units[-1][1]:
                pass                              # ىٰ ألف مقصورة
            elif units and units[-1][0] == 'و' and not units[-1][1]:
                units[-1] = ['ا', '']             # وٰ ← ا (الصَّلَوٰة)
            else:
                units.append(['ا', ''])
        elif ch in '۟۠':                # حرف زائد لا يُنطق
            if units:
                units.pop()
        elif ch == 'ٔ':                      # همزة فوق حرف
            if units:
                units[-1][0] = 'ء'
        elif ch in 'ۥۦۭ۪ۣۢٓۜ۫ۨ۬ ':
            pass                                  # علامات ضبط لا أثر لها في الوزن
        elif ch == 'ٱ':
            units.append(['ا', ''])
        elif ch == 'آ':
            units.append(['ء', FATHA]); units.append(['ا', ''])
        else:
            units.append([ch, ''])
        i += 1
    units = [u for u in units if u[0] != 'ـ']
    # ءَا في أول الكلمة لجذر مهموز الفاء: أَأْ (آمَنَ = أَأْمَنَ ← أَفْعَلَ)
    if (hamza_alif_as_double and root0_hamza and len(units) >= 2 and
            norm_hamza(units[0][0]) == 'ء' and units[1][0] == 'ا' and not units[1][1]):
        # الاسم المفرد بعد ءا حرف مكسور: آخِر ، آخِرَة ، آمِر ← فاعِل ؛ وغيره: آلِهَة ، آخَر ، آمَنَ ← أَفْعَل
        if not (hamza_alif_as_double == 'noun_sing' and len(units) >= 3 and KASRA in units[2][1]):
            units[1] = ['ء', SUKUN]
    # إِيـ / أُو في أول الكلمة لجذر مهموز الفاء: إِيمان = إِئْمان ← إِفْعَال
    if (root0_hamza and len(units) >= 3 and norm_hamza(units[0][0]) == 'ء' and
            units[1][0] in 'يو' and not units[1][1] and (KASRA in units[0][1] or DAMMA in units[0][1])):
        units[1] = ['ء', SUKUN]
    # ألف تنوين النصب ليست من البنية
    if len(units) >= 2 and units[-1] == ['ا', ''] and '\u064b' in units[-2][1]:
        units.pop()
    # كرسي الهمزة المتطرفة بعد ألف (شُرَكَاؤُ) ← ء
    if len(units) >= 2 and units[-1][0] in 'ؤئأ' and units[-2][0] == 'ا':
        units[-1][0] = 'ء'
    # الألف المتطرفة بعد ياء مفتوحة تُرسم ى (دُنْيَا ← دُنْيَى)
    if len(units) >= 2 and units[-1] == ['ا', ''] and units[-2][0] == 'ي' and FATHA in units[-2][1]:
        units[-1][0] = 'ى'
    # الياء غير المنقوطة في الرسم العثماني (نَبِىّ) ← ي
    for k, u in enumerate(units):
        if u[0] == 'ى' and (u[1] or k < len(units) - 1):
            u[0] = 'ي'
    if units:
        units[0][1] = units[0][1].replace(SHADDA, '')       # تشديد اللام الشمسية ليس من بنية الكلمة
    for k, u in enumerate(units):
        if k < len(units) - 1:
            for t, v in zip(TANWEEN, (FATHA, DAMMA, KASRA)):
                u[1] = u[1].replace(t, v)                    # تنوين في غير الآخر (هُدًى)
            if not u[1] and u[0] not in 'اى':
                prev = units[k - 1][1] if k else ''
                if not ((u[0] == 'و' and DAMMA in prev) or (u[0] == 'ي' and KASRA in prev)):
                    u[1] = SUKUN                             # سكون محذوف في الرسم (إخفاء/إدغام)
    return units


def expand_shadda(units):
    """الحرف المشدد = حرفان: الأول ساكن والثاني بحركته. نحتفظ بعلامة الربط."""
    out = []
    for k, (L, d) in enumerate(units):
        if SHADDA in d:
            out.append({'L': L, 'd': SUKUN, 'pair': k, 'half': 0})
            out.append({'L': L, 'd': d.replace(SHADDA, ''), 'pair': k, 'half': 1})
        else:
            out.append({'L': L, 'd': d, 'pair': None, 'half': None})
    return out


# ---------------------------------------------------------------- مطابقة حروف الجذر على حروف الكلمة
def match_cost(u, r):
    u, r = norm_hamza(u), norm_hamza(r)
    if u == r:
        return 0.0
    if r in WEAK:
        if u in 'وي':  return 0.25
        if u == 'ى':   return 0.2
        if u == 'ء':   return 0.35
        if u == 'ا':   return 0.8
    if r == 'ء':
        if u in 'اوي': return 0.6
    if r == 'و' and u == 'ت':
        return 0.9                 # إبدال الواو تاءً: اتَّقى ، تَقْوى
    if r == 'س' and u == 'ص':
        return 0.9                 # مُصَيْطِر ، بَصْطَة
    return None


def align(seq, root, ain_doubled=False):
    """أفضل مطابقة: لكل حرف جذر موضعه في الكلمة أو None (محذوف)."""
    n, m = len(seq), len(root)
    best = [None, 1e9]

    def unmatched_cost(idx_list):
        matched = [p for p in idx_list if p is not None]
        if not matched:
            return 1e9
        first, last = min(matched), max(matched)
        mset = set(matched)
        c = 0.0
        for p in range(n):
            if p in mset:
                continue
            L = seq[p]['L']
            dup = seq[p]['pair'] is not None and any(
                q in mset and seq[q]['pair'] == seq[p]['pair'] for q in (p - 1, p + 1) if 0 <= q < n)
            ifta3al = L in 'طد' and (p - 1) in mset and idx_list.index(p - 1) == 0 and p > 1
            if L not in AUGMENT and not dup and not ifta3al:
                c += 6
            if first < p < last:
                # نصف حرف مشدد مقابل لحرف جذر = تضعيف عين (فَعَّلَ) — زيادة مقبولة
                if seq[p]['pair'] is not None and any(
                        q in mset and seq[q]['pair'] == seq[p]['pair'] for q in (p - 1, p + 1) if 0 <= q < n):
                    c += 0.2
                elif L in 'اوي':
                    c += 0.3            # حروف المد زيادات شائعة (فاعِل، فَعِيل، فُعُول)
                else:
                    c += 1.0
            elif p < first:
                c += 0.1
            else:
                c += 0.05 * 0  # اللواحق في آخر الكلمة
        return c

    def rec(ri, start, acc, cost):
        if cost >= best[1]:
            return
        if ri == m:
            total = cost + unmatched_cost(acc)
            if total < best[1]:
                best[0], best[1] = list(acc), total
            return
        r = root[ri]
        for p in range(start, n):
            mc = match_cost(seq[p]['L'], r)
            # الحرف المشدد تضعيفٌ لعين الكلمة لا حرفان من الجذر (سَوَّى ← فَعَّلَ)، إلا في المضعّف
            # (ضالّ) وفي إدغام الفاء في العين (أَيَّام): فلا يُطابَق نصفه الثاني بحرف جذر آخر
            if (mc is not None and ri >= 2 and seq[p]['half'] == 1 and acc and acc[-1] == p - 1
                    and seq[p - 1]['pair'] == seq[p]['pair'] and root[ri] != root[ri - 1]
                    and norm_hamza(seq[p]['L']) == norm_hamza(root[ri - 1])
                    and (ain_doubled or any(match_cost(seq[x]['L'], r) is not None for x in range(p + 1, n)))):
                mc = None                                  # قُوَّة (فُعْلَة) تبقى: لا حرف بعدها يقوم مقام اللام
            if mc is not None:
                acc.append(p); rec(ri + 1, p + 1, acc, cost + mc); acc.pop()
        # حذف حرف الجذر: يجوز في المعتل والمهموز والمضعّف
        if norm_hamza(r) in WEAK + 'ء' or (ri > 0 and root[ri] == root[ri - 1]):
            acc.append(None); rec(ri + 1, start, acc, cost + 2.5); acc.pop()

    rec(0, 0, [], 0.0)
    return best[0], best[1]


def render(seq, alignment, root, act_pcpl=False, is_verb=False, fay3il=False, plural=False):
    """يحوّل المطابقة إلى وزن: حروف الجذر ← ف ع ل (ل)، والزوائد تبقى بحركاتها."""
    names = FA3LAL if len(root) == 4 else FA3L
    last_r = len(root) - 1
    pos2r = {p: k for k, p in enumerate(alignment) if p is not None}
    P = []   # قطع: dict(t=نص الحرف, d=حركة, r=رقم حرف الجذر أو None, madd=bool)

    def vowel_of(piece):
        return ''.join(ch for ch in piece['d'] if ch in FATHA + DAMMA + KASRA)

    i = 0
    while i < len(seq):
        u = seq[i]
        if u['pair'] is not None and u['half'] == 0 and i + 1 < len(seq):
            v = seq[i + 1]
            a, b = pos2r.get(i), pos2r.get(i + 1)
            if a is not None and b is not None and a == 0 and b == 1 and root[0] != root[1]:
                # حرفا جذر مختلفان أُدغم أحدهما في الآخر بعد القلب: أَيَّام = أَيْوَام ← أَفْعَال
                P.append(dict(t=names[a], d=SUKUN, r=a, madd=False))
                P.append(dict(t=names[b], d=v['d'], r=b, madd=False))
            elif a is not None and b is not None and a != b:
                # مضعّف: حرفا جذر مدغمان (أَحَبَّ = أَحْبَبَ ، ضالّ = ضالِل)
                prev = P[-1] if P else None
                if prev is not None and prev['r'] is not None and len(P) > 1 and vowel_of(prev):
                    va = vowel_of(prev); prev['d'] = SUKUN               # نقل الحركة إلى العين
                elif prev is not None and prev['r'] is not None and vowel_of(prev):
                    va = FATHA if is_verb else SUKUN                      # مَسَّ ← فَعَلَ ، رَبّ ← فَعْل
                elif prev is not None and prev['t'] == 'ا':
                    va = KASRA if (act_pcpl or plural) else FATHA         # فاعِل ، فَوَاعِل / فاعَلَ
                else:
                    va = FATHA
                P.append(dict(t=names[a], d=va, r=a, madd=False))
                P.append(dict(t=names[b], d=v['d'], r=b, madd=False))
            elif a is not None or b is not None:
                k = a if a is not None else b
                L, rl = u['L'], root[k]
                if k == last_r and L in 'وي' and rl in WEAK + 'ءأ':        # عَدُوّ ← فَعُول ، وَلِيّ ← فَعِيل
                    P.append(dict(t=L, d='', r=None, madd=False))
                    P.append(dict(t=names[k], d=v['d'], r=k, madd=False))
                elif fay3il and k == 1 and L == 'ي' and rl in WEAK and i == 1 and KASRA in v['d']:        # طَيِّب ، لَيِّن ← فَيْعِل
                    P.append(dict(t='ي', d=SUKUN, r=None, madd=False))
                    P.append(dict(t=names[k], d=v['d'], r=k, madd=False))
                elif norm_hamza(L) == norm_hamza(rl):                     # تضعيف حرف الجذر (فَعَّلَ)
                    P.append(dict(t=names[k] + SHADDA, d=v['d'], r=k, madd=False))
                elif L in 'وي' and rl in WEAK:                            # سَيِّد ، سَيِّئَة ← فَيْعِل
                    P.append(dict(t=L, d=SUKUN, r=None, madd=False))
                    P.append(dict(t=names[k], d=v['d'], r=k, madd=False))
                else:                                                     # إبدال افتعل: مُتَّقِين ← مُفْتَعِل
                    P.append(dict(t=names[k], d=SUKUN, r=k, madd=False))
                    P.append(dict(t=L, d=v['d'], r=None, madd=False))
            else:                                                         # تضعيف حرف زائد
                P.append(dict(t=u['L'] + SHADDA, d=v['d'], r=None, madd=False))
            i += 2
            continue
        k = pos2r.get(i)
        if k is not None:
            d, madd = u['d'], False
            if u['L'] in 'اوي' and not d:
                madd = True
            if u['L'] in 'اى' and not d and k == last_r:
                d = FATHA                                                 # دَعَا ، هُدَى ← فَعَل / فُعَل
            P.append(dict(t=names[k], d=d, r=k, madd=madd))
        else:
            L = u['L']
            if L in 'طد' and (i - 1) in pos2r and pos2r[i - 1] == 0 and i > 1:
                L = 'ت'                                        # اصْطَفَى ، ازْدَادَ ← افْتَعَلَ
            if i == 0 and norm_hamza(L) == 'ء':
                L = 'إ' if KASRA in u['d'] else 'أ'
            P.append(dict(t=L, d=u['d'], r=None, madd=False))
        i += 1

    # الأجوف والمثال: حرف العلة الأصلي مدًّا في الوسط (يَقُولُ ← يَفْعُلُ ، مَقَام ← مَفْعَل ، قالَ ← فَعَلَ)
    for j, pc in enumerate(P):
        if pc['r'] == 0 and pc['madd']:
            pc['d'] = SUKUN                                    # مِيعَاد ← مِفْعَال ، مُوقِن ← مُفْعِل
            continue
        if pc['r'] is not None and pc['madd'] and pc['r'] < last_r and j > 0:
            prev = P[j - 1]
            pv = vowel_of(prev)
            src = seq_letter = None
            if prev['r'] is not None and j - 1 == 0:          # بعد فاء الكلمة في أولها: قالَ ، قِيلَ ، جُوع
                pc['d'] = FATHA if _was_alif(seq, alignment, pc['r']) else SUKUN
            elif pv and prev['r'] is not None:
                pc['d'] = pv; prev['d'] = SUKUN
            elif pv:                                           # اخْتَارَ ← افْتَعَلَ ، يَخْتَارُ ← يَفْتَعِلُ
                L0 = seq[alignment[pc['r']]]['L']
                pc['d'] = {'ا': FATHA, 'ي': KASRA, 'و': DAMMA}.get(L0, FATHA)
            else:
                pc['d'] = FATHA if _was_alif(seq, alignment, pc['r']) else SUKUN
    return ''.join(pc['t'] + pc['d'] for pc in P)


def _was_alif(seq, alignment, k):
    p = alignment[k]
    return p is not None and seq[p]['L'] == 'ا'


def strip_ending(w):
    """حذف علامة الإعراب/البناء الأخيرة (وألف تنوين النصب)."""
    if w.endswith('ا') and len(w) > 1 and w[-2] == 'ً':
        w = w[:-1]
    return w.rstrip(VOWELS_ONLY + SUKUN)


def undo_assimilation(stem, root, vf):
    """ردّ الإدغام في افتعل وتفعّل/تفاعل قبل الوزن:
    مُطَّلِع ← مُطْتَلِع ، اتَّخَذَ ← اءْتَخَذَ ، مُدَّكِر ← مُذْتَكِر  (افْتَعَلَ)
    مُدَّثِّر ← مُتَدَثِّر ، يَذَّكَّرُ ← يَتَذَكَّرُ ، اثَّاقَلْتُمْ ← اتَثَاقَلْتُمْ  (تَفَعَّلَ ، تَفَاعَلَ)"""
    if vf not in (5, 6, 8):
        return stem
    letters = [(i, ch) for i, ch in enumerate(stem) if '\u0621' <= ch <= '\u064a' or ch == 'ٱ']
    r0 = norm_hamza(root[0])
    for n, (i, ch) in enumerate(letters[:3]):
        j = i + 1
        marks = ''
        while j < len(stem) and stem[j] in HARAKAT:
            marks += stem[j]; j += 1
        if SHADDA not in marks:
            continue
        vowel = marks.replace(SHADDA, '')
        before = ''.join(c for _, c in letters[:n])
        if vf == 8 and (ch == root[0] or (r0 == 'ء' and ch == 'ت') or (ch in 'دت' and root[0] in 'ذدزث')):
            first = 'ء' if r0 == 'ء' else root[0]
            if ch == root[0] and 'ت' in stem[j:j + 3]:
                return stem          # افتعل ظاهر لا إدغام فيه
            return stem[:i] + first + SUKUN + 'ت' + vowel + stem[j:]
        if vf in (5, 6) and ch == root[0] and 'ت' not in before:
            return stem[:i] + 'ت' + FATHA + ch + vowel + stem[j:]
        if n > 0:
            return stem
    return stem


def compute_wazn(stem, root, root0_hamza_double=True, act_pcpl=False, is_verb=False, fay3il=False, plural=False,
                 ain_doubled=False):
    units = tokenize(stem, root0_hamza=norm_hamza(root[0]) == 'ء', hamza_alif_as_double=root0_hamza_double)
    seq = expand_shadda(units)
    al, cost = align(seq, list(root), ain_doubled)
    if al is None:
        return None, 99
    return strip_ending(render(seq, al, root, act_pcpl, is_verb, fay3il, plural)), cost


def mufrad(wazn, tags):
    """رد جمع السلامة والمثنى (ومنهما المضاف: والِدَيْ ، حاضِرِي) إلى المفرد:
    فاعِلُونَ ← فاعِل ، فاعِلات ← فاعِلَة ، عَيْنَيْنِ ← فَعْل ، جَنَّتَيْنِ ← فَعْلَة"""
    if wazn is None:
        return None
    bare = re.sub('[' + HARAKAT + ']', '', wazn)
    dual = bool(tags & {'D', 'MD', 'FD'})
    plural_m = 'MP' in tags
    if (plural_m or dual or 'P' in tags) and bare.endswith('لن') and len(bare) > 3:
        w = strip_ending(cut_letters(wazn, 1))          # غاوِينَ ، عالِينَ ← فاعِل (ناقص)
        if 'ACT_PCPL' in tags and len(w) > 2 and w[-2] == DAMMA:
            w = w[:-2] + KASRA + 'ل'                    # عادُونَ ← فاعِل
        return w
    fem = lambda k: cut_letters(wazn, k).rstrip(VOWELS_ONLY + SUKUN) + FATHA + 'ة'
    if dual:
        for suf, k in (('تان', 3), ('تين', 3)):
            if bare.endswith(suf) and len(bare) > 4:
                return fem(k)
        if bare.endswith(('تا', 'تي')) and len(bare) > 3 and bare[-3] in 'فعل':
            return fem(2)                                # جَنَّتَيْ ← فَعْلَة
        for suf in ('ان', 'ين'):
            if bare.endswith(suf) and len(bare) > 3 and bare[-3] in 'فعل':
                return strip_ending(cut_letters(wazn, 2))
        if bare.endswith(('ا', 'ي')) and len(bare) > 2 and bare[-2] in 'فعل':
            return strip_ending(cut_letters(wazn, 1))   # والِدَيْ ، عَيْنَيْ ← المفرد
    if plural_m:
        for suf in ('ون', 'ين'):
            if bare.endswith(suf) and len(bare) > 3:
                return strip_ending(cut_letters(wazn, 2))
        if bare.endswith(('و', 'ي')) and len(bare) > 2 and bare[-2] in 'فعل':
            return strip_ending(cut_letters(wazn, 1))   # ناكِسُو ، حاضِرِي (بالإضافة) ← فاعِل
    if 'FP' in tags and bare.endswith('ات') and len(bare) > 3:
        return fem(2)
    return wazn


def cut_letters(w, k):
    """حذف آخر k حروف (مع حركاتها)."""
    idx = len(w)
    cnt = 0
    while idx > 0 and cnt < k:
        idx -= 1
        if w[idx] not in HARAKAT:
            cnt += 1
    return w[:idx]


BAB_RE = re.compile('ف' + FATHA + 'ع([' + FATHA + DAMMA + KASRA + '])ل')
HOLLOW_FI3ILA = {}      # جذر أجوف ← True إن جاء مضارعه بالألف (يَخافُ ، يَشاءُ ، يَنامُ) فبابه فَعِلَ


def verb_past_form(vf, root, lemma, root_bab=None):
    if len(root) == 4:
        return VF_PAST_QUAD.get(vf, 'فَعْلَلَ')
    if vf == 1:
        if root[1] in WEAK and HOLLOW_FI3ILA.get(root):
            return 'فَعِلَ'                              # خافَ ، شاءَ ، نامَ ← فَعِلَ
        w, _ = compute_wazn(lemma, root)
        m = BAB_RE.match(w or '')
        if m and not (root[1] in WEAK and m.group(1) == FATHA):
            return 'فَع' + m.group(1) + 'لَ'
        if root_bab and root_bab.get(root):
            return root_bab[root]                        # اللمّة مبنية للمجهول: الباب من صيغ الماضي المعلوم للجذر
        return ('فَع' + m.group(1) + 'لَ') if m else 'فَعَلَ'
    return VF_PAST.get(vf)


def collect_babs(words):
    """باب الثلاثي المجرد لكل جذر من الماضي المعلوم الوارد في المدونة، وعلامة الأجوف المفتوح العين في المضارع."""
    votes = defaultdict(Counter)
    for segs in words.values():
        for g, form, pos, feats in segs:
            if pos != 'V' or 'VF:1' not in feats or 'PASS' in feats.split('|'):
                continue
            parts = feats.split('|')
            kv = dict(p.split(':', 1) for p in parts if ':' in p)
            root = kv.get('ROOT')
            if not root or len(root) != 3:
                continue
            if 'PERF' in parts and root[1] not in WEAK:
                w, _ = compute_wazn(form, root, is_verb=True)
                m = BAB_RE.match(w or '')
                if m:
                    votes[root]['فَع' + m.group(1) + 'لَ'] += 1
            if 'IMPF' in parts and root[1] in WEAK:
                units = tokenize(form)
                letters = [u[0] for u in units]
                # يَخَافُ: حرف المضارعة ثم فاء الكلمة ثم ألف
                if len(letters) >= 3 and norm_hamza(letters[1]) == norm_hamza(root[0]) and letters[2] == 'ا':
                    HOLLOW_FI3ILA[root] = True
    return {r: c.most_common(1)[0][0] for r, c in votes.items()}


def stem_key(pos, root, stem):
    """معرّف ثابت للكلمة في ملف المراجعة: نوعها وجذرها وجذعها دون حركة الآخر وعلامات الضبط.
    لا يعتمد على الوزن المحسوب، فتبقى التصحيحات صالحة إن تغيّرت قواعد الاستخراج."""
    t = re.sub('[\u06df-\u06ed\u0653\u0654ـ]', '', stem or '').replace('ٱ', 'ا').replace('ٰ', 'ا')
    t = t.rstrip(VOWELS_ONLY + SUKUN)
    if len(t) > 1 and t[1] == SHADDA:
        t = t[0] + t[2:]
    return f'{pos}|{root}|{t}'


def load_corrections(path):
    """يقرأ ورقة «للمراجعة» من ملف التصحيحات: {المعرّف: (الحالة، الوزن الصحيح)}."""
    import os
    if not path or not os.path.exists(path):
        return {}
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True)['للمراجعة']
    rows = ws.iter_rows(values_only=True)
    head = [str(h or '').strip() for h in next(rows)]
    ik, ist, iw = head.index('المعرّف'), head.index('الحالة'), head.index('الوزن الصحيح')
    out = {}
    for r in rows:
        if not r or not r[ik]:
            continue
        st = str(r[ist] or '').strip()
        wz = ' '.join(str(r[iw] or '').split())
        if wz or st == 'صحيح':
            out[str(r[ik]).strip().replace('ٰ', 'ا')] = (st, wz)
    return out


# ---------------------------------------------------------------- قراءة ملف المدونة
# الملف الأصلي (quranic-corpus-morphology-0.4.txt) مكتوب بترميز Buckwalter الموسَّع للمدونة
BW = {"'": 'ء', '>': 'أ', '&': 'ؤ', '<': 'إ', '}': 'ئ', 'A': 'ا', 'b': 'ب', 'p': 'ة', 't': 'ت', 'v': 'ث',
      'j': 'ج', 'H': 'ح', 'x': 'خ', 'd': 'د', '*': 'ذ', 'r': 'ر', 'z': 'ز', 's': 'س', '$': 'ش', 'S': 'ص',
      'D': 'ض', 'T': 'ط', 'Z': 'ظ', 'E': 'ع', 'g': 'غ', '_': 'ـ', 'f': 'ف', 'q': 'ق', 'k': 'ك', 'l': 'ل',
      'm': 'م', 'n': 'ن', 'h': 'ه', 'w': 'و', 'Y': 'ى', 'y': 'ي', 'F': 'ً', 'N': 'ٌ', 'K': 'ٍ', 'a': 'َ',
      'u': 'ُ', 'i': 'ِ', '~': 'ّ', 'o': 'ْ', '`': 'ٰ', '{': 'ٱ', '^': 'ٓ', '#': 'ٔ', ':': 'ۜ', '@': '۟',
      '"': '۠', '[': 'ۢ', ';': 'ۣ', ',': 'ۥ', '.': 'ۦ', '!': 'ۨ', '-': '۪', '+': '۫', '%': '۬', ']': 'ۭ'}
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12}
NOUN_POS = {'N', 'PN', 'ADJ', 'IMPN', 'T', 'LOC', 'PRON', 'DEM', 'REL'}


def bw2ar(t):
    return ''.join(BW.get(ch, ch) for ch in t)


def read_corpus(src):
    """يقرأ ملف المدونة بأيٍّ من صيغتيه ويرد {(سورة، آية، كلمة): [(مقطع، الصورة، النوع، السمات)]}:
    - الأصلية من corpus.quran.com (Buckwalter، والموقع بين قوسين) فتُحوَّل إلى الحرف العربي؛
    - أو المنشورة بالحرف العربي (quran-morphology.txt)."""
    words = defaultdict(list)
    for line in open(src, encoding='utf-8-sig'):
        line = line.rstrip('\r\n')
        if not line or line.startswith('#') or line.startswith('LOCATION'):
            continue
        loc, form, pos, feats = line.split('\t')[:4]
        if loc.startswith('('):                         # الصيغة الأصلية
            form, pos, feats = convert_original(form, pos, feats)
        s, a, w, g = map(int, loc.strip('()').split(':'))
        words[(s, a, w)].append((g, form, pos, feats))
    return words


def convert_original(form, tag, feats):
    parts = [p.strip() for p in feats.split('|') if p.strip()]
    out, ptype, kv_pos = [], parts[0] if parts else '', None
    if ptype == 'PREFIX':
        out.append('PREF')
    elif ptype == 'SUFFIX':
        out.append('SUFF')
    pcpl = 'PCPL' in parts
    for p in parts[1:]:
        if p.startswith('POS:'):
            kv_pos = p[4:]
            if kv_pos in ('PN', 'ADJ', 'T', 'LOC', 'IMPN'):
                out.append(kv_pos)
        elif p.startswith('(') and p.endswith(')') and p[1:-1] in ROMAN:
            out.append(f'VF:{ROMAN[p[1:-1]]}')
        elif p.startswith(('LEM:', 'ROOT:', 'SP:')):
            k, v = p.split(':', 1)
            v = bw2ar(v)
            if k == 'ROOT':
                v = v.replace('ا', 'أ')                 # همزة الجذر تُكتب A في المدونة
            out.append(f'{k}:{v}')
        elif p == 'PCPL':
            continue
        elif p in ('ACT', 'PASS') and pcpl:
            out.append(p + '_PCPL')
        else:
            out.append(p)
    pos = 'V' if (kv_pos or tag) == 'V' else ('N' if (kv_pos or tag) in NOUN_POS else 'P')
    if pos == 'V' and ptype == 'STEM' and not any(x.startswith('VF:') for x in out):
        out.insert(0, 'VF:1')                            # الصيغة الأولى غير معلَّمة في الملف الأصلي
    if pos == 'N' and any(x in out for x in ('ACT_PCPL', 'PASS_PCPL', 'VN')) and not any(x.startswith('VF:') for x in out):
        out.insert(0, 'VF:1')                            # مشتقات المجرد كذلك (آكِل ، مَأْتِيّ)
    return bw2ar(form), pos, '|'.join(out)


def category(tags, pos):
    if pos == 'V':
        return 'فعل'
    if 'PN' in tags:   return 'علم'
    if 'ACT_PCPL' in tags:  return 'اسم فاعل'
    if 'PASS_PCPL' in tags: return 'اسم مفعول'
    if 'VN' in tags:   return 'مصدر'
    if 'ADJ' in tags:  return 'صفة'
    return 'اسم'


# ---------------------------------------------------------------- البناء
def main(src, dst, corrections_path='تصحيحات_الأوزان.xlsx'):
    corrections = load_corrections(corrections_path)
    n_corrected = 0
    words = read_corpus(src)

    root_bab = collect_babs(words)
    ayat = defaultdict(list)
    rows = []
    for (s, a, w), segs in sorted(words.items()):
        segs.sort()
        word_text = ''.join(f for _, f, _, _ in segs)
        ayat[(s, a)].append(word_text)
        for g, form, pos, feats in segs:
            parts = feats.split('|')
            tags = set(p for p in parts if ':' not in p)
            kv = dict(p.split(':', 1) for p in parts if ':' in p)
            root = kv.get('ROOT')
            if not root or pos not in ('N', 'V') or 'PREF' in tags or 'SUFF' in tags:
                continue
            vf = int(kv['VF']) if 'VF' in kv else (1 if pos == 'V' else None)
            double = not ('ACT_PCPL' in tags and vf == 1)        # آخِر (فاعِل) لا أَفْعَل
            if double and pos == 'N' and not tags & {'P', 'MP', 'FP'} and vf in (None, 1):
                double = 'noun_sing'
            opts = dict(act_pcpl='ACT_PCPL' in tags, is_verb=pos == 'V',
                        fay3il=pos == 'N' and vf in (None, 1) and 'PASS_PCPL' not in tags,
                        plural=bool(tags & {'P', 'MP', 'FP'}),
                        ain_doubled=vf in (2, 5))          # فَعَّلَ وتَفَعَّلَ: التشديد على العين
            form2 = undo_assimilation(form, root, vf)
            wz, cost = compute_wazn(form2, root, double, **opts)
            if wz is None:   # حرف جذر مدغم في سابقة/لاحقة (كُنتُم ، الَّيْل)
                tries = [compute_wazn(c, root, double, **opts)
                         for c in (root[0] + FATHA + form2, form2 + root[-1])]
                wz, cost = min(tries, key=lambda t: t[1])
                cost += 3
            if wz and pos == 'N' and wz.endswith(FATHA + 'ت') and 'FP' not in tags and 'FD' not in tags:
                wz = wz[:-1] + 'ة'          # التاء المفتوحة في الرسم العثماني (رَحْمَت)
            if wz and vf == 8 and 'تْف' in wz:
                wz = wz.replace('تْف', 'فْت', 1)   # اتَّبَعَ = اتْتَبَعَ ← افْتَعَلَ
            if wz and 'PN' in tags and cost > 3:
                wz = None                   # علم لا يتضح وزنه (الله ، إبراهيم ...)
            if wz and SUKUN in wz[1:2] and wz[0] in 'فعل':
                wz = 'ا' + wz               # ابْن ، اسْم بعد فصل همزة الوصل: فْع ← افْع
            if wz and 'PASS_PCPL' in tags and vf == 1 and root[-1] in WEAK:
                wz = wz.replace('مَفْعِيل', 'مَفْعُول')   # مَرْضِيّ ، مَأْتِيّ ← مَفْعُول
            if wz and pos == 'N' and root[-1] in WEAK and wz.endswith('ع') and len(wz) > 3 and not wz.startswith('افْ'):
                # المنقوص: حُذفت لامه في الرسم (مُعْتَدٍ ، الْجَوَارِ ، مُنَادِ ، تَرَاضٍ) فيُردّ إلى وزنه التام
                wz = wz + (DAMMA if 'VN' in tags else KASRA) + 'ل'
            if wz and pos == 'N' and root[-1] in WEAK and tags & {'P', 'MP', 'FP'} and wz == 'أَفْعِل':
                wz = 'أَفْعُل'              # أَيْدِي ← أَفْعُل (جمع منقوص)
            wz_m = mufrad(wz, tags) if pos == 'N' else wz
            conf = round(max(0.0, 1 - cost / 10), 2)
            corr = corrections.get(stem_key(pos, root, form))
            if corr:
                st_c, wz_c = corr
                if wz_c in ('-', '—', 'لا وزن'):      # لا وزن له (اسم فعل ونحوه)
                    wz = wz_m = None
                elif wz_c:                            # تصحيح المراجع
                    if pos == 'N':
                        if wz == wz_m:
                            wz = wz_c
                        wz_m = wz_c
                    else:
                        wz = wz_m = wz_c
                conf = 1.0                            # كلمة رُوجعت: لا تُوسم بـ ≈
                n_corrected += 1
            rows.append(dict(
                sura=s, aya=a, word_no=w, word=word_text, stem=form, root=root,
                lemma=kv.get('LEM'), pos=pos, category=category(tags, pos), vf=vf,
                wazn=wz,                                    # وزن الكلمة كما وردت (دون السوابق واللواحق والإعراب)
                wazn_mufrad=wz_m,
                wazn_fi3l=verb_past_form(vf, root, kv.get('LEM', ''), root_bab) if pos == 'V' else None,
                passive=1 if 'PASS' in tags else 0,
                confidence=conf,
                tags='|'.join(parts)))

    if __import__('os').path.exists(dst):
        __import__('os').remove(dst)
    con = sqlite3.connect(dst)
    c = con.cursor()
    c.executescript('''
    CREATE TABLE suwar (sura INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE ayat  (sura INTEGER, aya INTEGER, text TEXT, PRIMARY KEY (sura, aya));
    CREATE TABLE words (
        id INTEGER PRIMARY KEY, sura INTEGER, aya INTEGER, word_no INTEGER,
        word TEXT, stem TEXT, root TEXT, lemma TEXT, pos TEXT, category TEXT, vf INTEGER,
        wazn TEXT, wazn_mufrad TEXT, wazn_fi3l TEXT, passive INTEGER, confidence REAL, tags TEXT);
    CREATE TABLE awzan (kind TEXT, wazn TEXT, label TEXT, count INTEGER, PRIMARY KEY (kind, wazn));
    ''')
    c.executemany('INSERT INTO suwar VALUES (?,?)', list(enumerate(SURA_NAMES, 1)))
    c.executemany('INSERT INTO ayat VALUES (?,?,?)', [(s, a, ' '.join(ws)) for (s, a), ws in sorted(ayat.items())])
    cols = list(rows[0].keys())
    c.executemany(f'INSERT INTO words ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                  [tuple(r[k] for k in cols) for r in rows])
    c.executescript('''
    CREATE INDEX ix_w_wazn   ON words(wazn);
    CREATE INDEX ix_w_mufrad ON words(wazn_mufrad);
    CREATE INDEX ix_w_fi3l   ON words(wazn_fi3l);
    CREATE INDEX ix_w_loc    ON words(sura, aya);
    ''')
    # جدول القائمة المنسدلة
    fi3l = Counter(r['wazn_fi3l'] for r in rows if r['pos'] == 'V' and r['wazn_fi3l'])
    ism = Counter(r['wazn_mufrad'] for r in rows if r['pos'] == 'N' and r['category'] != 'علم' and r['wazn_mufrad'])
    sigha = Counter(r['wazn'] for r in rows if r['wazn'] and r['category'] != 'علم')
    for kind, cnt in (('فعل', fi3l), ('اسم', ism), ('صيغة', sigha)):
        c.executemany('INSERT INTO awzan VALUES (?,?,?,?)',
                      [(kind, w, w, n) for w, n in cnt.items()])
    con.commit()
    if corrections:
        print('التصحيحات المطبقة:', n_corrected, 'كلمة من', len(corrections), 'سطرًا')
    print('words:', len(rows), '| فعل:', len(fi3l), '| اسم:', len(ism), '| صيغة:', len(sigha))
    con.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or ['تصحيحات_الأوزان.xlsx']))
