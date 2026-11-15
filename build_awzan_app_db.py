# -*- coding: utf-8 -*-
"""
بناء قاعدة الأوزان لتطبيق الأندرويد (awzan_app.db) من quran_awzan.db.
نسخة مخففة: بلا الجذع واللمّة والأوسمة ونص المدونة؛ ومعها أعمدة الوزن دون حركات (للبحث بلا تشكيل)
وعدد كلمات المدونة في كل آية (لمواءمة الترقيم مع النص المشكول وتمييز الكلمة).
الاستعمال:  python build_awzan_app_db.py [quran_awzan.db] [awzan_app.db]
ثم ضع awzan_app.db في assets، وارفع awzanDbVersion في database_helper.dart.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime

HARAKAT_RE = re.compile('[ً-ْٰ]')


def bare(s):
    return HARAKAT_RE.sub('', s) if s else s


def main(src='quran_awzan.db', dst='awzan_app.db'):
    if os.path.exists(dst):
        os.remove(dst)
    a = sqlite3.connect(src)
    b = sqlite3.connect(dst)
    b.executescript('''
    CREATE TABLE words (sura INTEGER, aya INTEGER, word_no INTEGER, word TEXT, root TEXT, pos TEXT, category TEXT,
                        wazn TEXT, wazn_mufrad TEXT, wazn_fi3l TEXT,
                        wazn_b TEXT, wazn_mufrad_b TEXT, wazn_fi3l_b TEXT, approx INTEGER);
    CREATE TABLE awzan (kind TEXT, wazn TEXT, count INTEGER);
    CREATE TABLE ayat_n (sura INTEGER, aya INTEGER, n INTEGER, PRIMARY KEY (sura, aya));
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    ''')
    rows = a.execute('''SELECT sura, aya, word_no, word, root, pos, category, wazn, wazn_mufrad, wazn_fi3l, confidence
                        FROM words WHERE wazn IS NOT NULL OR wazn_fi3l IS NOT NULL ORDER BY id''').fetchall()
    b.executemany('INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  [(s, ay, wn, w, r, p, c, wz, wm, wf, bare(wz), bare(wm), bare(wf), 1 if (cf or 0) < 0.7 else 0)
                   for s, ay, wn, w, r, p, c, wz, wm, wf, cf in rows])
    b.executemany('INSERT INTO awzan VALUES (?,?,?)', a.execute('SELECT kind, wazn, count FROM awzan').fetchall())
    b.executemany('INSERT INTO ayat_n VALUES (?,?,?)',
                  [(s, ay, len(t.split(' '))) for s, ay, t in a.execute('SELECT sura, aya, text FROM ayat')])
    b.execute("INSERT INTO meta VALUES ('built_at', ?)", (datetime.now().isoformat(timespec='seconds'),))
    # بلا فهارس عمدًا: 50 ألف صف تُمسح في جزء من الثانية، والفهارس تضاعف حجم القاعدة في التطبيق
    b.commit()
    b.execute('VACUUM')
    b.close()
    print(f'{dst}: {len(rows)} كلمة، {os.path.getsize(dst) / 1e6:.1f} MB')


if __name__ == '__main__':
    main(*sys.argv[1:3])
