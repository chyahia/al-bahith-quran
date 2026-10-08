import sqlite3
import os
import sys
import re

# السوابق المسموح بتجاهلها عند الاستبعاد
PREFIXES = ["", "و", "ف", "ب", "ك", "ل", "ال", "وال", "فال", "بال", "كال", "لل", "ول", "فل", "وب", "فب"]
DIACRITICS_REGEX = re.compile(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]')

# آيات الاندماج المعروفة (سليمة كما هي)
MASAQ_MERGED_WORD_NO = {
    (3, 75): 19, (5, 13): 17, (5, 24): 7, (5, 96): 13, (5, 117): 16,
    (11, 107): 3, (16, 109): 1,
    (2, 181): 3,
    (13, 37): 8,
    (3, 112): 4,
    (8, 6): 4,
    (23, 44): 5,
    (37, 130): 3,
}

MASAQ_SPLIT_WORD_NO = {
    (7, 61): 2,
}

# تحويلات صريحة لكلمات بعينها؛ ما لم يُذكر يبقى رقمه كما هو. None = لا مقابل لها في MASAQ
MASAQ_WORD_OVERRIDES = {
    (19, 31): {4: 3, 10: 9},
    (40, 38): {4: 5},
    (37, 102): {17: 18},
}

def adjust_word_no_for_masaq(sura_id, aya_num, true_word_no):
    # 1) تحويلات صريحة (لها الأولوية)
    ov = MASAQ_WORD_OVERRIDES.get((sura_id, aya_num))
    if ov is not None:
        return ov.get(true_word_no, true_word_no)

    # 2) دمج: كلمتان في quran.db صارتا واحدة في MASAQ
    merge_point = MASAQ_MERGED_WORD_NO.get((sura_id, aya_num))
    if merge_point is not None:
        if true_word_no <= merge_point:
            return true_word_no
        elif true_word_no == merge_point + 1:
            return merge_point
        else:
            return true_word_no - 1

    # 3) فصل: كلمة في quran.db صارت اثنتين في MASAQ
    split_point = MASAQ_SPLIT_WORD_NO.get((sura_id, aya_num))
    if split_point is not None:
        if true_word_no < split_point:
            return true_word_no
        return true_word_no + 1

    return true_word_no

def split_shared_word_segments(s_id, a_num, w_num, m_word, segs, word_of=lambda seg: seg[3]):
    """
    حين يحمل رقم واحد في MASAQ كلمتين من quran.db (غافر 38: قَوْمِ + اتَّبِعُونِ،
    الصافات 102: أَبَتِ + افْعَلْ)، يعيد مقاطع الكلمة w_num وحدها بحسب ترتيبها.
    يستعملها التبويب 1 (مقاطع tuples) والتبويب 2 (مقاطع dicts عبر word_of).
    لا تعتمد على حروف الجذر، فتعمل مع UNSTABLE_ROOTS أيضًا (مثل «أبو»).
    """
    sharers = sorted(w for w in range(max(1, m_word - 3), m_word + 4)
                     if adjust_word_no_for_masaq(s_id, a_num, w) == m_word)
    if len(sharers) < 2:
        return segs
    # تجميع بحسب قيمة Word (بترتيب أول ظهور)، لا بالتتالي: في غافر 38 تتخلل
    # مقاطعُ «قَوْمِ» مقطعَ «اتَّبِعُونِ»؛ والمقطع بلا Word يلحق بمجموعة سابقه
    groups, order, last = {}, [], None
    for seg in segs:
        word = word_of(seg) or last
        if word not in groups:
            groups[word] = []
            order.append(word)
        groups[word].append(seg)
        last = word
    groups = [groups[k] for k in order]
    if len(groups) != len(sharers) or w_num not in sharers:
        return segs  # دمج حقيقي في كلمة واحدة (بعدما...)، تُصنَّف كاملة
    return groups[sharers.index(w_num)]


BUILT_LABELS = {'مبني', 'INVARIABLE'}
BUILT_CASE_VALUES = {'INVARIABLE'}
UNSTABLE_ROOTS = {'موه', 'كون', 'ذكر', 'سطر', 'ذخر', 'شفه', 'ابو'}

def get_db_connection(db_name):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    db_path = os.path.join(base_path, db_name)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

HAMZA_ALEF_VARIANTS = ('أ', 'إ', 'آ')

def strip_diacritics(word):
    clean = DIACRITICS_REGEX.sub('', word)
    for h in HAMZA_ALEF_VARIANTS:
        clean = clean.replace(h, 'ا')
    return clean

def get_char_diacritics(word):
    res = []
    current_char = None
    current_diacs = set()
    for char in word:
        if not DIACRITICS_REGEX.match(char):
            if current_char is not None:
                res.append((current_char, current_diacs))
            current_char = char
            current_diacs = set()
        else:
            if current_char is not None:
                current_diacs.add(char)
    if current_char is not None:
        res.append((current_char, current_diacs))
    return res

def should_exclude(word_tashkeel, ex_words_data):
    word_clean = strip_diacritics(word_tashkeel)
    for ex in ex_words_data:
        ex_c = ex['clean']
        if word_clean.endswith(ex_c):
            prefix = word_clean[:-len(ex_c)] if len(word_clean) > len(ex_c) else ""
            if prefix in PREFIXES:
                user_chars = get_char_diacritics(ex['tashkeel'])
                word_chars = get_char_diacritics(word_tashkeel)
                word_chars_suffix = word_chars[-len(user_chars):]
                if len(user_chars) == len(word_chars_suffix):
                    match = True
                    for (u_char, u_diacs), (w_char, w_diacs) in zip(user_chars, word_chars_suffix):
                        if not u_diacs.issubset(w_diacs):
                            match = False
                            break
                    if match:
                        return True
    return False

def is_clitic(mtag):
    if not mtag or mtag == 'NONE':
        return True
    mtag = str(mtag).upper()
    if 'PRON' in mtag or 'PREF' in mtag or 'SUFF' in mtag:
        return True
    exact_clitics = {'NOON_V5', 'INTERROG', 'PART_INTERROG', 'CONJ', 'PREP',
                     'EMPH', 'VOC', 'NEG', 'FUT', 'INC'}
    if mtag in exact_clitics:
        return True
    return False

def is_affix_tag(tag):
    if tag is None:
        return True
    t = str(tag).strip()
    if t == '' or t.upper() == 'NONE':
        return True
    tu = t.upper()
    if 'PREF' in tu or 'SUFF' in tu:
        return True
    if tu in {'DET', 'SUBJ_PRON', 'POSS_PRON'}:
        return True
    if tu.startswith('CASE_'):
        return True
    if is_clitic(tu):
        return True
    return False

# المرجع الوحيد لأوسمة الفعل في البرنامج كله (يستوردها app.py وأدوات الفحص).
# مستخرجة من جرد Morph_Tag في MASAQ.db: كانت هنا PV/IV/CV فقط، فلم يُعرف
# المبني للمجهول ولا الجامد جذعًا مقدَّمًا، وقد تُختار بادئة المضارعة جذعًا قبله.
VERB_TAGS = {'PV', 'IV', 'CV', 'PV_PASS', 'IV_PASS', 'UNINFLECTED_VERB'}
VERB_CORE_TAGS = VERB_TAGS

# حرف المضارعة حين يُوسم مقطعًا مستقلًا بالشخص (IV3MS، IV3MP، IV1P...)، وهو بادئة لا جذع.
# (نظيره IMPERF_PREF يستبعده شرط 'PREF' أصلًا.)
IMPERF_PERSON_PREFIX_RE = re.compile(r'^IV\d')

def is_imperf_person_prefix(tag):
    return bool(IMPERF_PERSON_PREFIX_RE.match(str(tag or '').strip().upper()))

# ---- تصنيف المقاطع والكلمات (اسم/فعل) لإحصاء التبويب 1، منقول من app.py ----
PARTICLE_OR_FUNCTION_TAGS = {
    'PREP', 'CONJ', 'NEG_PART', 'SUBJUNC_PART', 'JUSSIVE_PART', 'CERT_PART', 'ANNUL_PART',
    'INF_ANNUL_PART', 'VOC_PART', 'EXCEPT_PART', 'CONDITION_PART', 'FUT_PART', 'FUTURE_PART',
    'YES_NO_RESP_PART', 'INTERROG', 'PART_INTERROG', 'INTERROG_PART', 'OTHER',
    'EMPHATIC_NUN', 'PROTECT_NUN', 'NOON_V5',
    # أوسمة أدوات يعرفها grammar_engine.is_clitic (التبويب 2) وكانت غائبة هنا،
    # فكانت تُحسب "اسمًا" وتحجب الفعل بعدها (مثل لام التوكيد في لَيَقُولُنَّ)
    'EMPH', 'VOC', 'NEG', 'FUT', 'INC',
    # من جرد Morph_Tag الفعلي في MASAQ.db: أدوات غابت عن هذه القائمة
    'FUTUR_PART', 'INF_SUBJUNC_PART', 'KAAFA_MAKFOUFA', 'PART', 'PREFIX',
}
# من grammar_engine (مرجع واحد). أُزيل IV3MS وIV3FS: هما بادئتا مضارعة لا جذعان،
# وكانا يجعلان المضارع المبني للمجهول يُعنوَن «فعل مضارع» مبنيًا للمعلوم.
VERB_CORE_TAGS_STATS = VERB_TAGS  # اسم قديم أُبقي للتوافق


def classify_masaq_segment(morph_tag, case_mood):
    """
    يصنّف مقطعًا واحدًا من MASAQ.db: ('noun', تسمية الحالة) أو ('verb', تسمية الزمن)
    أو None إن كان أداة أو ضميرًا أو مقطعًا بنيويًا بحتًا (لاحقة/سابقة/علامة حالة).
    """
    if not morph_tag or str(morph_tag).strip().lower() in ('none', ''):
        return None
    tag = str(morph_tag).strip().upper()

    if 'PRON' in tag:
        return None
    if 'PREF' in tag or 'SUFF' in tag or tag.startswith('CASE_') or tag == 'DET':
        return None
    if tag in PARTICLE_OR_FUNCTION_TAGS:
        return None
    if is_imperf_person_prefix(tag):  # حرف المضارعة (IV3MP، IV1P...): بادئة لا جذع
        return None

    if tag in VERB_CORE_TAGS_STATS:
        if tag in ('PV', 'PV_PASS'):
            label = 'فعل ماضٍ' + (' مبني للمجهول' if tag == 'PV_PASS' else '')
        elif tag == 'CV':
            label = 'فعل أمر'
        elif tag == 'UNINFLECTED_VERB':
            label = 'فعل جامد'
        else:  # IV, IV_PASS
            label = 'فعل مضارع' + (' مبني للمجهول' if tag == 'IV_PASS' else '')
        return ('verb', label)

    # أي وسم آخر لم يُستبعد أعلاه هو جذع اسمي حقيقي (اسم ذات/معنى/علم/فاعل/مفعول/صفة/مصدر...)
    cm = (case_mood or '').strip().upper()
    if cm == 'NOMINATIVE':
        return ('noun', 'اسم (مرفوع)')
    elif cm == 'ACCUSATIVE':
        return ('noun', 'اسم (منصوب)')
    elif cm == 'GENITIVE':
        return ('noun', 'اسم (مجرور)')
    else:
        return ('noun', 'اسم (غير محدد الحالة)')


# جذوع أسماء الأدوات ذات الجذور في root_words (من قائمة الأداة السادسة: أيّ 215، كيف 83، أنّى 28، كُلَّمَا 16)
NOMINAL_FUNCTION_TAGS = {'INTERROG_PRON', 'INTERROG_PART', 'REL_PRON', 'CONDITION_PART'}
NOMINAL_FUNCTION_LABEL = 'اسم أداة (استفهام، نداء، شرط)'


def classify_word_kind(tag_case_pairs):
    """
    يصنّف كلمة كاملة كما يفعل إحصاء التبويب 1: ('noun'|'verb', التسمية) أو None.
    tag_case_pairs: [(Morph_Tag, Case_Mood), ...] لمقاطع الكلمة (بعد split_shared_word_segments).
    الفعل يُقدَّم أينما وقع (فلا تحجبه بادئة المضارعة أو أداة سابقة)، وإلا فأول جذع اسمي.
    """
    classified = [r for r in (classify_masaq_segment(t, cm) for t, cm in tag_case_pairs) if r is not None]
    if not classified:
        # كلمة ذات جذر بلا اسم ولا فعل بالمعنى الصرفي الضيق، لكن جذعها اسم في النحو:
        # «كيف» و«أنّى» و«أيّ» (استفهام، و«يا أيها»)، و«كُلَّمَا». تُعدّ اسمًا بعنوان خاص.
        # قرار عرض لا تعديل بيانات: الوسوم في MASAQ تبقى كما هي. والحرف الحقيقي («لات» NEG_PART)
        # يبقى خارج اللوحة.
        for t, _ in tag_case_pairs:
            if str(t or '').strip().upper() in NOMINAL_FUNCTION_TAGS:
                return ('noun', NOMINAL_FUNCTION_LABEL)
        return None
    verbs = [r for r in classified if r[0] == 'verb']
    return verbs[0] if verbs else classified[0]

# ألفاظ تبقى "اسم علم" في Morph_Tag لكن تُدرَج أيضًا ضمن نتائج "الأسماء الحسنى"
# عند البحث، دون تغيير وسمها الفعلي في القاعدة (لفظ الجلالة والرحمن أعلام أصلًا)
DIVINE_NAME_PROPER_NOUNS = {'الله', 'الرحمن'}

# تصنيف الموقع النحوي إلى الأبواب التقليدية الأربعة، لدعم اختيار "كل المرفوعات" ونظائرها
SYNTACTIC_ROLE_GROUPS = {
    'GROUP_RAFI': {'AGNT', 'PASS_SUBJ', 'SUBJ', 'SUBJ_DELA', 'PRED', 'SUBJ_COP_V', 'PART_COP_PRED'},
    'GROUP_NASB': {'OBJ', 'COGN', 'PURP', 'CIRCUM', 'ACC_SPECIF', 'EXCP', 'ADV_TIME', 'ADV_PLCE',
                   'VOC', 'SUBJ_NEG_CAT', 'SUBJ_COP_PART', 'V_COP_PRED'},
    'GROUP_JARR': {'PREP_OBJ', 'GEN_CONS'},
    'GROUP_TAWABI': {'ADJ', 'CONJ_N', 'APPOS', 'INTENCIF', 'CONFIRM_LAFDHI'},
}

# المواقع الإعرابية الحقيقية (أبواب المرفوعات والمنصوبات والمجرورات والتوابع)
IRAB_ROLES = set().union(*SYNTACTIC_ROLE_GROUPS.values())

def _fallback_stem(segments):
    """
    مرحلة احتياطية: تعمل فقط حين لا يجد pick_stem_segment جذعًا
    (كلمات كل مقاطعها من نوع أداة/ضمير: كيف، في، من، الذي، عند...).
    تفضّل مقطعًا له دور نحوي حقيقي، وتتجنب حرف العطف ما أمكن.
    """
    if not segments:
        return None

    def role_of(seg):
        return str(seg['Syntactic_Role'] or '').strip().upper()

    def tag_of(seg):
        return str(seg['Morph_Tag']).strip().upper()

    with_role = [s for s in segments if role_of(s) not in ('', 'NONE', 'NON_INFLECT')]
    for seg in with_role:
        if tag_of(seg) != 'CONJ':
            return seg
    if with_role:
        return with_role[0]

    for seg in segments:
        if tag_of(seg) != 'CONJ':
            return seg
    return segments[0]

def pick_stem_segment(segments):
    for seg in segments:
        if str(seg['Morph_Tag']).strip().upper() in VERB_CORE_TAGS:
            return seg
    # أولويات الاختيار بعد الفعل (منطق مبني على بيانات القاعدة نفسها):
    #  1) مقطع له موقع إعرابي حقيقي (من أبواب SYNTACTIC_ROLE_GROUPS، أو أي موقع على اسم/فعل).
    #  2) اسم أو فعل بلا موقع (بمصنِّف التبويب 1 نفسه).
    #  3) حرف موقعه وظيفة الحرف نفسه لا محل إعرابي (VOC_PART 352 مرة على «يا»، PREP على
    #     واو القسم وتائه ولام التوكيد، CONJ، CERT_PART، ANNUL_PART...)؛ ويؤخذ آخرها لأنه
    #     الأقرب إلى قلب الكلمة («ليت» في «يا ليتنا»، «إن» في «لَئِنْ»).
    #  4) حرف بلا موقع.  5) مقطع موقعه NON_INFLECT (لا محل له).
    # كانت «يا» في «يَابَنِي» واللام في «لَآيَاتٍ» والواو في «فَوَرَبِّكَ» تُختار جذعًا قبل الاسم
    # (359 موضع جذر كشفتها أداة «مقارنة نوع الكلمة»).
    best_content = None
    particle_roles = []
    best_other = None
    best_no_role = None
    for seg in segments:
        if is_affix_tag(seg['Morph_Tag']):
            continue
        role = str(seg['Syntactic_Role'] or '').strip().upper()
        is_content = classify_masaq_segment(seg['Morph_Tag'], seg['Case_Mood']) is not None
        if role == 'NON_INFLECT':
            if best_no_role is None:
                best_no_role = seg
            continue
        if role and role != 'NONE':
            if is_content or role in IRAB_ROLES:
                return seg
            particle_roles.append(seg)
            continue
        if is_content:
            if best_content is None:
                best_content = seg
        elif best_other is None:
            best_other = seg
    for candidate in (best_content, particle_roles[-1] if particle_roles else None,
                      best_other, best_no_role):
        if candidate is not None:
            return candidate
    return _fallback_stem(segments)

def pick_stem_for_root(segments, strong_root_chars):
    """
    عند البحث بالجذر: إن اشتركت كلمتان في رقم واحد (عمود Word مختلف بين المقاطع)،
    نقتصر على مقاطع الكلمة التي تحمل حروف الجذر، ثم نختار الجذع بالقاعدة العامة.
    سابقًا كانت ترجع أول مقطع غير لاحق تحمل كلمته حروف الجذر، وعمود Word واحد لكل
    مقاطع الكلمة عادةً، فكانت تختار لام التوكيد أو حرف الاستقبال (OTHER، FUT_PART)
    قبل الفعل في «لَقُضِيَ» و«سَيُغْفَرُ» و«لَبِئْسَ».
    """
    if strong_root_chars and len({seg['Word'] for seg in segments}) > 1:
        own = [seg for seg in segments
               if strong_root_chars.issubset(set(strip_diacritics(seg['Word'] or '')))]
        if own:
            segments = own
    return pick_stem_segment(segments)

# ---------------------------------------------------------------------------
# مستويا الشروط في البحث النحوي (القسم 19 من السجل):
#  - الوسم الصرفي والموقع النحوي والحالة الإعرابية: على الجذع وحده (الكلمة نفسها).
#  - «الضمير المتصل بالكلمة»: على ضمائرها المتصلة (ومنها المحذوفة رسمًا في صفوف Other_i3rab).
# ---------------------------------------------------------------------------
GROUP_NOUNS = 'GROUP_NOUNS'
GROUP_VERBS = 'GROUP_VERBS'
ATTACHED_ROLES = ('AGNT', 'PASS_SUBJ', 'OBJ', 'GEN_CONS', 'PREP_OBJ', 'SUBJ_COP_PART', 'SUBJ_COP_V')
_NOUN_TAGS_CACHE = None


def noun_tags(conn):
    """كل أوسمة الأسماء الموجودة في القاعدة: ما يصنّفه classify_masaq_segment اسمًا
    (تعريف «الاسم» نفسه في لوحة التبويب 1). تُحسب مرة واحدة."""
    global _NOUN_TAGS_CACHE
    if _NOUN_TAGS_CACHE is None:
        tags = [r[0] for r in conn.execute("SELECT DISTINCT Morph_Tag FROM MASAQ") if r[0] is not None]
        _NOUN_TAGS_CACHE = {t for t in tags if (classify_masaq_segment(t, None) or ('',))[0] == 'noun'}
    return _NOUN_TAGS_CACHE


def morph_tag_set(morph_tag, conn):
    """الأوسمة التي يقبلها اختيار «الوسم الصرفي»، أو None للاختيار الفردي العادي."""
    if morph_tag == GROUP_VERBS:
        return VERB_TAGS
    if morph_tag == GROUP_NOUNS:
        return noun_tags(conn)
    if morph_tag == 'NOUN_PROP':
        # «اسم علم» يشمل العربي والأعجمي؛ و«علم أعجمي» (NOUN_PROP_FOREIGN) اختيار مستقل
        return {'NOUN_PROP', 'NOUN_PROP_FOREIGN'}
    return None


def is_attached_pronoun(seg):
    """مقطع ضمير متصل: وسمه ضمير أو لاحقة فاعل/مفعول للفعل، أو صف Other_i3rab (وسمه النص 'None')."""
    t = str(seg['Morph_Tag'] or 'None').upper()
    # اصطلاح القاعدة: حين تُحذف واو الجماعة قبل نون التوكيد يوضع موقع الفاعل المحذوف على النون
    # («لَيُؤْمِنُنَّ»: 31 موضعًا)؛ فالنون التي تحمل موقع ضمير تُعدّ ضميرًا متصلًا، والحرفية (NON_INFLECT) لا.
    if t == 'EMPHATIC_NUN':
        return str(seg['Syntactic_Role']) in ATTACHED_ROLES
    return 'PRON' in t or 'SUFF_SUBJ' in t or 'SUFF_DO' in t or t == 'NONE'


def search_grammar(filters):
    masaq_conn = get_db_connection('MASAQ.db')
    quran_conn = get_db_connection('quran.db')

    search_text = filters.get('search_text', '').strip()
    search_type = filters.get('search_type', 'contains')

    excluded_words_input = filters.get('excluded_words', '').strip()
    ex_words_data = []
    if excluded_words_input:
        for w in excluded_words_input.split():
            w_strip = w.strip()
            if w_strip:
                ex_words_data.append({'clean': strip_diacritics(w_strip), 'tashkeel': w_strip})

    valid_root_locations = set()
    # رقم MASAQ -> أرقام الكلمات الأصلية في root_words التي تُحوَّل إليه
    root_origins = {}
    strong_root_chars = set()
    
    if search_text and search_type == 'root':
        clean_root = search_text.replace(" ", "")
        # استخراج الحروف الصلبة للجذر كبصمة تأكيد لمنع الانزياح (يحل مشكلة المحسنين)
        strong_root_chars = set(c for c in clean_root if c not in ' اأإآىءؤئوية')
        # جذور معتلة/مبدلة تتغير حروفها في الكلمة، فنعتمد فيها على مطابقة الموضع وحدها
        if clean_root in UNSTABLE_ROOTS:
            strong_root_chars = set()
        
        quran_cur = quran_conn.cursor()
        quran_cur.execute("""
            SELECT rw.sura_id, rw.aya_num, rw.word_location 
            FROM root_words rw 
            JOIN roots r ON rw.root_id = r.id 
            WHERE REPLACE(r.arabic_trilateral, ' ', '') = ?
        """, (clean_root,))
        for r in quran_cur.fetchall():
            try:
                s_id = int(r['sura_id'])
                v_id = int(r['aya_num'])
                w_num = int(r['word_location'].split(':')[2])
                adjusted_w_num = adjust_word_no_for_masaq(s_id, v_id, w_num)
                if adjusted_w_num is None:
                    continue
                valid_root_locations.add((s_id, v_id, adjusted_w_num))
                root_origins.setdefault((s_id, v_id, adjusted_w_num), set()).add(w_num)
            except Exception:
                pass

    # ================================================================
    # التعديل الجوهري: إلغاء فلاتر النحو من استعلام SQL
    # هذا يضمن وصول جميع مقاطع الكلمة لبايثون لاختيار الجذع بدقة
    # ================================================================
    query = """
        SELECT Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood 
        FROM MASAQ 
        WHERE 1=1
    """
    params = []

    sura_filter = filters.get('sura_filter', 'all')
    if sura_filter != 'all':
        query += " AND Sura_No = ?"
        params.append(int(sura_filter))

    query += " ORDER BY Sura_No ASC, Verse_No ASC, Word_No ASC"

    masaq_cur = masaq_conn.cursor()
    masaq_cur.execute(query, params)

    grouped = {}
    for row in masaq_cur.fetchall():
        key = (int(row['Sura_No']), int(row['Verse_No']), int(row['Word_No']))
        grouped.setdefault(key, []).append(dict(row))

    morph_tag = filters.get('morph_tag', 'all')
    syntactic_role = filters.get('syntactic_role', 'all')
    case_mood = filters.get('case_mood', 'all')
    attached_role = filters.get('attached_role', 'all') or 'all'
    morph_set = morph_tag_set(morph_tag, masaq_conn) if morph_tag != 'all' else None
    search_text_clean = strip_diacritics(search_text) if search_text else ""

    def _iter_word_groups():
        """عند البحث بالجذر: إن حمل رقم MASAQ كلمتين، نمرّر مقاطع الكلمة المقصودة وحدها
        إلى اختيار الجذع والفلاتر، فلا يُختار «افْعَلْ» لجذر «أبو» ولا «قَوْمِ» لفلتر الأمر."""
        for key, segs in grouped.items():
            if search_text and search_type == 'root':
                origins = root_origins.get(key)
                if not origins:
                    continue  # ليس موضعًا للجذر أصلًا (كان يُستبعد لاحقًا على أي حال)
                for w in sorted(origins):
                    yield key, split_shared_word_segments(
                        key[0], key[1], w, key[2], segs, word_of=lambda seg: seg['Word'])
            else:
                yield key, segs

    final_masaq_rows = []
    for (s_id, v_id, w_id), segs in _iter_word_groups():

        if search_text and search_type == 'root':
            stem = pick_stem_for_root(segs, strong_root_chars)
        else:
            stem = pick_stem_segment(segs)
        if stem is None:
            continue

        word_tashkeel = stem['Word']
        word_clean = strip_diacritics(word_tashkeel)

        if ex_words_data and should_exclude(word_tashkeel, ex_words_data):
            continue

        if search_text:
            if search_type == 'root':
                if (s_id, v_id, w_id) not in valid_root_locations:
                    continue
                # التأكد من بصمة الجذر (يطرد كلمة "المحسنين" فوراً)
                if strong_root_chars:
                    if not strong_root_chars.issubset(set(word_clean)):
                        continue
            else:
                if search_type == 'exact' and word_clean != search_text_clean:
                    continue
                elif search_type == 'contains' and search_text_clean not in word_clean:
                    continue

        # الشروط الثلاثة على الجذع وحده (الكلمة نفسها، لا ضمائرها المتصلة)
        stem_tag = str(stem['Morph_Tag'])
        stem_role = str(stem['Syntactic_Role'] or 'None')

        if morph_tag != 'all':
            if morph_set is not None:
                if stem_tag not in morph_set:
                    continue
            elif morph_tag == 'NOUN_DIVINE_NAME':
                # لفظ الجلالة والرحمن ضمن «الأسماء الحسنى» دون تغيير وسمهما (يبقيان اسم علم)
                if not (stem_tag == 'NOUN_DIVINE_NAME' or
                        (stem_tag == 'NOUN_PROP' and any(word_clean.endswith(n) for n in DIVINE_NAME_PROPER_NOUNS))):
                    continue
            elif stem_tag != morph_tag:
                continue

        if syntactic_role != 'all':
            if syntactic_role in SYNTACTIC_ROLE_GROUPS:
                if stem_role not in SYNTACTIC_ROLE_GROUPS[syntactic_role]:
                    continue
            elif stem_role != syntactic_role:
                continue

        # الضمائر المتصلة بالكلمة ومواقعها (للفلتر الرابع وللعرض)
        pronoun_roles = [str(seg['Syntactic_Role']) for seg in segs
                         if seg is not stem and is_attached_pronoun(seg)
                         and str(seg['Syntactic_Role']) in ATTACHED_ROLES]
        if attached_role != 'all' and attached_role not in pronoun_roles:
            continue

        # الفلترة بالحالة تُطبق على الجذع فقط (يحل مشكلة الأفعال المضارعة)
        if case_mood != 'all':
            raw = (stem['Case_Mood'] or '').strip()
            if case_mood in BUILT_LABELS:
                if raw not in BUILT_CASE_VALUES:
                    continue
            else:
                if raw != case_mood:
                    continue

        final_masaq_rows.append(dict(stem, _pronoun_roles=pronoun_roles))

    unique_ayahs = list(set([(row['Sura_No'], row['Verse_No']) for row in final_masaq_rows]))
    ayah_dict = {}
    quran_cur = quran_conn.cursor()
    for s_id, v_id in unique_ayahs:
        quran_cur.execute('''
            SELECT a.text_uthmani, a.text_tashkeel, a.text_clean, s.name as sura_name 
            FROM ayas a JOIN suras s ON a.sura_id = s.id 
            WHERE a.sura_id = ? AND a.aya_num = ?
        ''', (s_id, v_id))
        aya_data = quran_cur.fetchone()
        if aya_data:
            ayah_dict[f"{s_id}_{v_id}"] = aya_data

    results = []
    for row in final_masaq_rows:
        key = f"{row['Sura_No']}_{row['Verse_No']}"
        aya_data = ayah_dict.get(key)
        if aya_data:
            results.append({
                'sura_no': row['Sura_No'],
                'verse_no': row['Verse_No'],
                'word_no': row['Word_No'],
                'word_text': row['Word'],
                'morph_tag': row.get('Morph_Tag', ''),
                'syntactic_role': row.get('Syntactic_Role', ''),
                'case_mood': row.get('Case_Mood', ''),
                'pronoun_roles': row.get('_pronoun_roles', []),
                'sura_name': aya_data['sura_name'],
                'text_uthmani': aya_data['text_uthmani'],
                'text_tashkeel': aya_data['text_tashkeel'],
                'text_clean': aya_data['text_clean']
            })

    masaq_conn.close()
    quran_conn.close()

    return {
        'count': len(results),
        'results': results
    }





