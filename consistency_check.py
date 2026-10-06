# -*- coding: utf-8 -*-
"""
فحص التماسك الداخلي لقاعدة MASAQ.db
يطبّق أربع قواعد منطقية آلية بحتة (بلا ذكاء اصطناعي) لاكتشاف تناقضات محتملة
بين الوسم الصرفي (Morph_Tag) والحالة الإعرابية (Case_Mood) والموقع النحوي (Syntactic_Role).

هذا الملف لا يُصحّح شيئًا تلقائيًا، فقط يكتشف ويُبلِّغ.
"""
import sqlite3
from grammar_engine import get_db_connection

# ---------------------------------------------------------------------------
# تصنيف المواقع النحوية حسب الحالة الإعرابية المتوقعة لها
# ---------------------------------------------------------------------------
NOMINATIVE_ROLES = {'AGNT', 'SUBJ', 'SUBJ_DELA', 'PRED', 'SUBJ_COP_V'}
ACCUSATIVE_ROLES = {'OBJ', 'COGN', 'PURP', 'CIRCUM', 'ACC_SPECIF',
                     'VOC', 'SUBJ_NEG_CAT', 'V_COP_PRED'}
# الظرف (زمان/مكان) يُستبعد من اشتراط النصب: إن سبقه حرف جر حقيقي (كـ"من قبلُ"،
# "من بعدُ") خرج عن الظرفية إلى الجر الصريح، فتكون حالته الإعرابية مجرورة بحق لا
# محلاً، وهذا مشروع لا خطأ (تحقق مباشرةً في فحص "قَبْلُ" و"حَيْثُ")
# ADV_TIME/ADV_PLCE: قد يُجر الظرف بحرف جر حقيقي ("من قبلُ") فيخرج عن الظرفية.
# SUBJ_COP_PART: وسم يخلط بين "اسم إنّ/ليت" (منصوب) و"اسم ما" الحجازية
# (مرفوع، لأنها تعمل عمل ليس)، فلا يمكن توقّع حالة واحدة له دون تمييزهما أولاً.
# PASS_SUBJ: قد يُجر نائب الفاعل بحرف جر زائد ("استُهزئ برسلٍ")، وهذا مقرَّر عمدًا
# PART_COP_PRED: نفس مشكلة SUBJ_COP_PART، يخلط بين خبر إنّ (مرفوع) وخبر ما
# الحجازية (منصوب، لأنها تعمل عمل ليس)
NO_CASE_EXPECTATION_ROLES = {'ADV_TIME', 'ADV_PLCE', 'SUBJ_COP_PART', 'PASS_SUBJ', 'PART_COP_PRED'}
GENITIVE_ROLES = {'PREP_OBJ', 'GEN_CONS'}
# التوابع تتبع ما قبلها في إعرابه، فلا حالة ثابتة متوقعة لها؛ تُستبعد من قاعدة الحالة/الموقع
TAWABI_ROLES = {'ADJ', 'CONJ_N', 'APPOS', 'INTENCIF', 'CONFIRM_LAFDHI'}

CONTENT_ROLES = NOMINATIVE_ROLES | ACCUSATIVE_ROLES | GENITIVE_ROLES | TAWABI_ROLES | NO_CASE_EXPECTATION_ROLES

# أوسمة صرفية تمثّل "أداة" لا "جذعًا" (حرف جر، عطف، أداة تعريف، حرف ناسخ...)
# أوسمة صرفية تمثّل "أداة" خالصة لا محتوى مستقلاً أبدًا (لا استثناءات معروفة لها)
# استُبعدت عمدًا: NEG_PART, OTHER, CONDITION_PART — لأن "ما" ونظائرها قد تكون
# هي نفسها الاسم المُعرَب (موصولة، نكرة تامة، حجازية)، كما تقرر صراحة في مراجعة النواسخ
TOOL_MORPH_TAGS = {
    'PREP', 'CONJ', 'DET', 'VOC_PART', 'SUBJUNC_PART',
    'JUSSIVE_PART', 'CERT_PART', 'ANNUL_PART', 'INF_ANNUL_PART',
    'EXCEPT_PART', 'FUT_PART', 'FUTURE_PART', 'YES_NO_RESP_PART',
}

RULE_LABELS = {
    'CASE_ROLE_MISMATCH': 'تعارض الموقع النحوي مع الحالة الإعرابية',
    'TOOL_SEGMENT_CONTENT_ROLE': 'مقطع أداة يحمل حكم الجذع',
    'DUP_SUBJ_PRED': 'ازدواج مبتدأ/خبر داخل الكلمة نفسها',
    'VERB_WITH_IRAB_CASE': 'فعل ماضٍ/أمر بحالة إعرابية غير منطقية',
}

# ---------------------------------------------------------------------------
# استثناءات معتمدة: مواضع راجعها إنسان بعناية وقرر أنها صحيحة أو مقبولة ضمن
# خلاف نحوي معتبر، فلا داعي لتكرار ظهورها في كل فحص قادم. كل سطر: (ID, Segment_No)
# مع سبب القرار وتاريخه، للتوثيق لا للمنطق (المنطق يعتمد فقط على المجموعة أدناه).
# أضِف هنا فقط بعد مراجعة فردية حقيقية؛ لا تُستخدم لإخفاء نتائج لم تُراجَع بعد.
APPROVED_EXCEPTIONS = {
    # الكاف الاسمية بمعنى "مثل" (Morph_Tag=PREP تقنيًا، لكن الموقع النحوي صحيح)
    (46424, 1): "كدعاء (النور:63): الكاف اسم بمعنى مثل، مفعول به صحيح — 2026-10-01",
    (58864, 1): "كالمفسدين (ص:28): نفس اصطلاح الكاف الاسمية — 2026-10-01",
    (58870, 1): "كالفجار (ص:28): نفس اصطلاح الكاف الاسمية — 2026-10-01",
    (64779, 1): "كالذين (الجاثية:21): نفس اصطلاح الكاف الاسمية — 2026-10-01",
    (67719, 1): "كالرميم (الذاريات:42): نفس اصطلاح الكاف الاسمية — 2026-10-01",
    (7966, 1): "كالذين (آل عمران:105): نفس اصطلاح الكاف الاسمية — 2026-10-01",
    # اسم "ليت" الناسخة (الكلمة المركبة وُسمت وسمًا واحدًا بقرار متعمَّد)
    (46810, 1): "يا ليتني (الفرقان:27): اسم ليت، قرار دمج الكلمة المركبة — 2026-10-01",
    (46818, 1): "ليتني (الفرقان:28): اسم ليت، قرار دمج الكلمة المركبة — 2026-10-01",
    (55206, 1): "يا ليتنا (الأحزاب:66): اسم ليت، قرار دمج الكلمة المركبة — 2026-10-01",
    # التوكيد اللفظي المبتكَر عمدًا (الوسم الصرفي يبقى أنّ، والموقع توكيد لفظي)
    (44441, 1): "أنّكم (المؤمنون:35): توكيد لفظي متعمَّد، الوسم الصرفي الأصلي صحيح — 2026-10-01",
}



def _row_dict(r):
    return {
        'ID': r['ID'], 'Segment_No': r['Segment_No'],
        'Sura_No': r['Sura_No'], 'Verse_No': r['Verse_No'], 'Word_No': r['Word_No'],
        'Word': r['Word'], 'Morph_Tag': r['Morph_Tag'],
        'Syntactic_Role': r['Syntactic_Role'], 'Case_Mood': r['Case_Mood'],
    }


def run_consistency_check(limit_per_rule=2000):
    """
    يشغّل القواعد الأربع ويعيد قاموسًا: اسم القاعدة -> قائمة المواضع المشبوهة.
    limit_per_rule: سقف أمان لكل قاعدة لمنع استجابة ضخمة غير متوقعة.
    """
    conn = get_db_connection('MASAQ.db')
    cur = conn.cursor()
    results = {k: [] for k in RULE_LABELS}

    # ---- القاعدة 1: تعارض الموقع مع الحالة ----
    # يُستبعد PREP_OBJ من هذا الفحص: المجرور بحرف جر زائد يُسجَّل بحالته المحلية
    # (مرفوعًا أو منصوبًا حسب موقعه) لا بعلامة الجر الظاهرة، وهذا اصطلاح صحيح ومتسق
    # تقرر صراحة في مراجعة الاسم المجرور، فلا يصح اعتباره تعارضًا.
    def expected_case_for(role):
        if role in NOMINATIVE_ROLES:
            return 'NOMINATIVE'
        if role in ACCUSATIVE_ROLES:
            return 'ACCUSATIVE'
        if role == 'GEN_CONS':
            return 'GENITIVE'
        return None

    case_check_roles = NOMINATIVE_ROLES | ACCUSATIVE_ROLES | {'GEN_CONS'}
    placeholders = ",".join("?" for _ in case_check_roles)
    cur.execute(
        f"""SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood
            FROM MASAQ WHERE Syntactic_Role IN ({placeholders})""",
        list(case_check_roles),
    )
    for r in cur.fetchall():
        exp = expected_case_for(r['Syntactic_Role'])
        actual = (r['Case_Mood'] or '').strip()
        # نسمح بـ INVARIABLE لأنها قد تمثّل مبنيًا في المحل المتوقع نفسه (اصطلاح القاعدة الثابت)
        if actual and actual != exp and actual != 'INVARIABLE':
            if len(results['CASE_ROLE_MISMATCH']) < limit_per_rule:
                results['CASE_ROLE_MISMATCH'].append(_row_dict(r))

    # ---- القاعدة 2: مقطع أداة يحمل حكم الجذع ----
    tool_ph = ",".join("?" for _ in TOOL_MORPH_TAGS)
    content_ph = ",".join("?" for _ in CONTENT_ROLES)
    cur.execute(
        f"""SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood
            FROM MASAQ WHERE Morph_Tag IN ({tool_ph}) AND Syntactic_Role IN ({content_ph})""",
        list(TOOL_MORPH_TAGS) + list(CONTENT_ROLES),
    )
    for r in cur.fetchall():
        if len(results['TOOL_SEGMENT_CONTENT_ROLE']) < limit_per_rule:
            results['TOOL_SEGMENT_CONTENT_ROLE'].append(_row_dict(r))

    # ---- القاعدة 3: ازدواج مبتدأ/خبر على نفس الكلمة ----
    cur.execute(
        """SELECT Sura_No, Verse_No, Word_No,
                  GROUP_CONCAT(DISTINCT Syntactic_Role) as roles
           FROM MASAQ
           WHERE Syntactic_Role IN ('SUBJ','SUBJ_DELA','PRED')
           GROUP BY Sura_No, Verse_No, Word_No
           HAVING SUM(CASE WHEN Syntactic_Role IN ('SUBJ','SUBJ_DELA') THEN 1 ELSE 0 END) > 0
              AND SUM(CASE WHEN Syntactic_Role = 'PRED' THEN 1 ELSE 0 END) > 0"""
    )
    dup_words = cur.fetchall()
    for dw in dup_words:
        cur.execute(
            """SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood
               FROM MASAQ WHERE Sura_No=? AND Verse_No=? AND Word_No=?
               AND Syntactic_Role IN ('SUBJ','SUBJ_DELA','PRED')""",
            (dw['Sura_No'], dw['Verse_No'], dw['Word_No']),
        )
        for r in cur.fetchall():
            if len(results['DUP_SUBJ_PRED']) < limit_per_rule:
                results['DUP_SUBJ_PRED'].append(_row_dict(r))

    # ---- القاعدة 4: فعل بحالة إعرابية غير منطقية ----
    cur.execute(
        """SELECT ID, Segment_No, Sura_No, Verse_No, Word_No, Word, Morph_Tag, Syntactic_Role, Case_Mood
           FROM MASAQ WHERE Morph_Tag IN ('PV','CV')
           AND Case_Mood IN ('NOMINATIVE','ACCUSATIVE','GENITIVE')"""
    )
    for r in cur.fetchall():
        if len(results['VERB_WITH_IRAB_CASE']) < limit_per_rule:
            results['VERB_WITH_IRAB_CASE'].append(_row_dict(r))

    conn.close()

    # استبعاد المواضع المعتمَدة يدويًا كاستثناءات سليمة قبل حساب الملخص النهائي
    for rule_key in results:
        results[rule_key] = [
            r for r in results[rule_key]
            if (r['ID'], r['Segment_No']) not in APPROVED_EXCEPTIONS
        ]

    summary = {k: len(v) for k, v in results.items()}
    return {'summary': summary, 'labels': RULE_LABELS, 'issues': results}


def export_consistency_excel(issues_dict, sura_name_lookup):
    """
    يبني ملف Excel بنفس الصيغة التي اعتُمدت طوال مشروع المراجعة اليدوية
    (الملف / السورة / الآية / الكلمة / الوسم الحالي / القاعدة المخالَفة)،
    جاهزًا للصق مباشرة في محادثة مع أداة ذكاء اصطناعي للتحقق السياقي النهائي.
    """
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "فحص التماسك"
    headers = ["القاعدة", "السورة", "الآية", "الكلمة", "Morph_Tag", "Syntactic_Role", "Case_Mood", "ID", "Segment_No"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for rule_key, rows in issues_dict['issues'].items():
        rule_label = issues_dict['labels'][rule_key]
        for r in rows:
            sura_name = sura_name_lookup.get(r['Sura_No'], str(r['Sura_No']))
            ws.append([
                rule_label, sura_name, r['Verse_No'], r['Word'],
                r['Morph_Tag'], r['Syntactic_Role'], r['Case_Mood'],
                r['ID'], r['Segment_No'],
            ])

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    return wb
