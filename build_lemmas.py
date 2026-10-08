# -*- coding: utf-8 -*-
"""
يستخرج «اللمة» (الصيغة المعجمية) لكل كلمة من ملف المدونة القرآنية quranic-corpus-morphology-0.4.txt
ويضيفها إلى quran.db في جدول جديد word_lemmas. لا يمسّ أي جدول موجود.

لماذا: جدول morphology في quran.db لم تُنقل إليه خاصية LEM: من ملف المدونة، و«ملف الجذر» يحتاجها
لتجميع صيغ الجذر معجميًا (آمَنَ، مُؤْمِن، إِيمَان...) بدل الكلمات كما كُتبت.

الجدول: word_lemmas(sura_id, aya_num, word_num, lemma, lemma_bw, root, pos)
  - الترقيم ترقيم root_words (سورة:آية:كلمة)، وهو ترقيم المدونة نفسه إلا في آيات تعدّ فيها المدونة كلمتين
    كلمة واحدة («بَعْدَمَا» في البقرة 181 مثلًا) ويعدّهما root_words كلمتين. المرشحة لذلك آيات الدمج نفسها في
    MASAQ_MERGED_WORD_NO؛ ويختار السكربت لكل آية منها الترقيم الذي يطابق الجذور أكثر، ويطبع اختياره.
  - lemma بالحروف العربية (محوّلة من ترميز Buckwalter الموسَّع للمدونة)، وroot بحروف مفصولة بمسافة
    كما في جدول roots («ا م ن»).

الاستعمال (بجانب quran.db وملف المدونة):
    python build_lemmas.py            -> فحص للقراءة فقط: عدد الكلمات، عيّنة، ومطابقة الجذر مع root_words
    python build_lemmas.py --apply    -> نسخة احتياطية quran_backup_lemmas.db ثم إنشاء الجدول
"""
import sqlite3, sys, os, re
from collections import Counter

DB, BACKUP = 'quran.db', 'quran_backup_lemmas.db'
CORPUS = 'quranic-corpus-morphology-0.4.txt'

# ترميز Buckwalter الموسَّع كما في توثيق المدونة القرآنية
BW = {
    "'": 'ء', '|': 'آ', '>': 'أ', '&': 'ؤ', '<': 'إ', '}': 'ئ', 'A': 'ا', 'b': 'ب', 'p': 'ة',
    't': 'ت', 'v': 'ث', 'j': 'ج', 'H': 'ح', 'x': 'خ', 'd': 'د', '*': 'ذ', 'r': 'ر', 'z': 'ز',
    's': 'س', '$': 'ش', 'S': 'ص', 'D': 'ض', 'T': 'ط', 'Z': 'ظ', 'E': 'ع', 'g': 'غ', '_': 'ـ',
    'f': 'ف', 'q': 'ق', 'k': 'ك', 'l': 'ل', 'm': 'م', 'n': 'ن', 'h': 'ه', 'w': 'و', 'Y': 'ى',
    'y': 'ي', 'F': 'ً', 'N': 'ٌ', 'K': 'ٍ', 'a': 'َ', 'u': 'ُ', 'i': 'ِ', '~': 'ّ', 'o': 'ْ',
    '`': 'ٰ', '{': 'ٱ', '^': 'ٓ', '#': 'ٔ', ':': 'ۜ', '@': '۟', '"': '۠', '[': 'ۢ', ';': 'ۣ',
    ',': 'ۥ', '.': 'ۦ', '!': 'ۨ', '-': '۪', '+': '۫', '%': '۬', ']': 'ۭ',
}


def bw2ar(s):
    return ''.join(BW.get(c, c) for c in s)


def norm_root(r):
    """توحيد للمقارنة: الهمزات كلها ألف، والياء المقصورة ياء، دون مسافات."""
    r = r.replace(' ', '')
    for h in 'أإآءؤئ':
        r = r.replace(h, 'ا')
    return r.replace('ى', 'ي')


if not os.path.exists(CORPUS):
    print(f"لم يُعثر على {CORPUS} بجانب السكربت.")
    sys.exit(1)

# آيات الدمج في MASAQ (نسخة من grammar_engine.MASAQ_MERGED_WORD_NO): (سورة، آية) -> رقم الكلمة المدموجة
MERGED_CANDIDATES = {
    (3, 75): 19, (5, 13): 17, (5, 24): 7, (5, 96): 13, (5, 117): 16, (11, 107): 3, (16, 109): 1,
    (2, 181): 3, (13, 37): 8, (3, 112): 4, (8, 6): 4, (23, 44): 5, (37, 130): 3,
}

raw = {}
loc_re = re.compile(r'^\((\d+):(\d+):(\d+):(\d+)\)$')
with open(CORPUS, encoding='utf-8') as f:
    for line in f:
        if line.startswith('#') or not line.strip() or line.startswith('LOCATION'):
            continue
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 4:
            continue
        m = loc_re.match(parts[0])
        if not m:
            continue
        feats = parts[3].split('|')
        if 'STEM' not in feats:
            continue
        s, a, w = int(m.group(1)), int(m.group(2)), int(m.group(3))
        lem = next((x[4:] for x in feats if x.startswith('LEM:')), None)
        root = next((x[5:] for x in feats if x.startswith('ROOT:')), None)
        pos = next((x[4:] for x in feats if x.startswith('POS:')), parts[2])
        if lem is None:
            continue
        # كلمة واحدة قد يكون فيها جذع واحد فقط في المدونة؛ إن تكرر نأخذ الأول
        raw.setdefault((s, a, w), (bw2ar(lem), lem, ' '.join(bw2ar(root)) if root else None, pos))

# جذور root_words لاختيار ترقيم كل آية مرشحة
conn = sqlite3.connect(DB)
cur = conn.cursor()
rw_roots = {}
for s, a, loc, root in cur.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral
                                     FROM root_words rw JOIN roots r ON rw.root_id = r.id"""):
    try:
        rw_roots[(int(s), int(a), int(loc.split(':')[2]))] = root
    except Exception:
        pass


def agreement(s, a, shift_after):
    n = 0
    for (cs, ca, cw), v in raw.items():
        if (cs, ca) != (s, a) or v[2] is None:
            continue
        w = cw + 1 if (shift_after is not None and cw > shift_after) else cw
        r = rw_roots.get((s, a, w))
        if r is not None and norm_root(r) == norm_root(v[2]):
            n += 1
    return n


shift = {}
print("آيات الدمج المرشحة (مطابقة الجذور: بلا إزاحة / بإزاحة بعد الكلمة المدموجة):")
for (s, a), mpos in sorted(MERGED_CANDIDATES.items()):
    keep, moved = agreement(s, a, None), agreement(s, a, mpos)
    if moved > keep:
        shift[(s, a)] = mpos
    print(f"   {s}:{a}  {keep} / {moved}  -> {'إزاحة' if moved > keep else 'كما هي'}")

rows = {}
for (s, a, w), v in raw.items():
    mpos = shift.get((s, a))
    rows[(s, a, w + 1 if (mpos is not None and w > mpos) else w)] = v

print(f"كلمات لها لمة في المدونة: {len(rows)}")
print("عيّنة (البقرة 3):", [(k[2], v[0], v[2], v[3]) for k, v in sorted(rows.items()) if k[:2] == (2, 3)])

# مطابقة الجذر مع root_words (للتحقق من وحدة الترقيم)
agree = disagree = missing = 0
samples = []
missing_roots = Counter()
missing_samples = []
for s, a, loc, root in cur.execute("""SELECT rw.sura_id, rw.aya_num, rw.word_location, r.arabic_trilateral
                                     FROM root_words rw JOIN roots r ON rw.root_id = r.id"""):
    try:
        w = int(loc.split(':')[2])
    except Exception:
        continue
    v = rows.get((int(s), int(a), w))
    if v is None or v[2] is None:
        missing += 1
        missing_roots[root] += 1
        if len(missing_samples) < 8:
            missing_samples.append(((s, a, w), root, 'لا لمة' if v is None else f'لمة بلا جذر: {v[0]} ({v[3]})'))
        continue
    if norm_root(v[2]) == norm_root(root):
        agree += 1
    else:
        disagree += 1
        if len(samples) < 10:
            samples.append(((s, a, w), root, v[2], v[0]))
total = agree + disagree
print(f"مطابقة جذر المدونة مع root_words: {agree} من {total} ({100 * agree / max(total, 1):.2f}%)"
      f"، ولا لمة أو لا جذر في المدونة: {missing}")
for x in samples:
    print("   مختلف:", x)
if missing:
    print("   أكثر الجذور فيما لا جذر له في المدونة:", missing_roots.most_common(10))
    for x in missing_samples:
        print("   بلا جذر:", x)

lemma_count = Counter(v[0] for v in rows.values())
print(f"لمات مختلفة: {len(lemma_count)}")

if '--apply' not in sys.argv:
    print("\nفحص فقط. للتنفيذ (والبرنامج مغلق): python build_lemmas.py --apply")
    sys.exit(0)
if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='word_lemmas'").fetchone():
    print("الجدول word_lemmas موجود مسبقًا: توقف دون تعديل.")
    sys.exit(1)
if os.path.exists(BACKUP):
    print(f"{BACKUP} موجودة مسبقًا: لن تُستبدل. توقف.")
    sys.exit(1)
bk = sqlite3.connect(BACKUP)
conn.backup(bk)
bk.close()
print(f"\nنسخة احتياطية: {BACKUP}")
cur.execute("""CREATE TABLE word_lemmas (
    sura_id INTEGER, aya_num INTEGER, word_num INTEGER,
    lemma TEXT, lemma_bw TEXT, root TEXT, pos TEXT,
    PRIMARY KEY (sura_id, aya_num, word_num))""")
cur.executemany("INSERT INTO word_lemmas VALUES (?,?,?,?,?,?,?)",
                [(k[0], k[1], k[2], *v) for k, v in sorted(rows.items())])
conn.commit()
n = cur.execute("SELECT COUNT(*) FROM word_lemmas").fetchone()[0]
print(f"أُنشئ الجدول word_lemmas: {n} صفًا (المتوقع {len(rows)}).")
conn.close()
