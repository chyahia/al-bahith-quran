import io
import base64
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches

def create_word_document(query, query2, results, display_type, stats_data=None, stats_data2=None, chart_image_mushaf=None, chart_image_rev=None, grammar_data=None, collocations=None, notes=None):
    if notes is None:
        notes = {}

    doc = Document()

    # --- إجبار اتجاه القسم كله RTL ---
    sectPr = doc.sections[0]._sectPr
    if sectPr.find(qn('w:bidi')) is None:
        sectPr.append(OxmlElement('w:bidi'))

    # --- الإصلاح الحاسم لمشكلة المحاذاة في Word 2010 ---
    settings_element = doc.settings.element
    theme_font_lang = settings_element.find(qn('w:themeFontLang'))
    if theme_font_lang is not None:
        theme_font_lang.set(qn('w:bidi'), 'ar-SA')

    def make_rtl(p):
        pPr = p._p.get_or_add_pPr()
        bidi = OxmlElement('w:bidi')
        pPr.append(bidi)
        mark_rPr = OxmlElement('w:rPr')
        mark_rtl = OxmlElement('w:rtl')
        mark_rPr.append(mark_rtl)
        pPr.append(mark_rPr)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def set_run_rtl(run, cs_font=None):
        run.font.rtl = True
        rPr = run._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.append(rFonts)
        font_name = cs_font or run.font.name or 'Arial'
        rFonts.set(qn('w:cs'), font_name)
        rFonts.set(qn('w:hint'), 'cs')
        if run.font.size is not None:
            half_points = run.font.size.pt * 2  
            szCs = rPr.find(qn('w:szCs'))
            if szCs is None:
                szCs = OxmlElement('w:szCs')
                rPr.append(szCs)
            szCs.set(qn('w:val'), str(int(half_points)))

    title = doc.add_paragraph()
    make_rtl(title)
    
    title_text = f'\u200Fالتقرير الشامل والنتائج لـ: "{query}"\u200F\n'
    if query2:
        title_text = f'\u200Fتقرير المقارنة بين: "{query}" و "{query2}"\u200F\n'
        
    run_title = title.add_run(title_text)
    run_title.font.size = Pt(18)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(27, 94, 32)
    set_run_rtl(run_title)

    meta = doc.add_paragraph()
    make_rtl(meta)
    meta_run = meta.add_run(f'\u200Fإجمالي الآيات المستخرجة: {len(results)}\u200F\n')
    meta_run.font.size = Pt(12)
    set_run_rtl(meta_run)

    RLM = "\u200F"

    # ================= 1. إضافة الرسوم البيانية كصور =================
    if chart_image_mushaf or chart_image_rev:
        p_img_title = doc.add_paragraph()
        make_rtl(p_img_title)
        r_img_title = p_img_title.add_run(f"{RLM}1. التحليل البياني للانتشار:{RLM}")
        r_img_title.font.bold = True
        r_img_title.font.size = Pt(14)
        r_img_title.font.color.rgb = RGBColor(27, 94, 32)
        set_run_rtl(r_img_title)

        def insert_chart(b64_str, sub_title):
            try:
                p_sub = doc.add_paragraph()
                make_rtl(p_sub)
                r_sub = p_sub.add_run(f"{RLM}- {sub_title}:{RLM}")
                r_sub.font.bold = True
                set_run_rtl(r_sub)
                
                image_data = base64.b64decode(b64_str.split(',')[1])
                image_stream = io.BytesIO(image_data)
                p_pic = doc.add_paragraph()
                p_pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run_pic = p_pic.add_run()
                run_pic.add_picture(image_stream, width=Inches(6.0))
            except: pass

        if chart_image_mushaf: insert_chart(chart_image_mushaf, 'حسب ترتيب المصحف')
        if chart_image_rev: insert_chart(chart_image_rev, 'حسب ترتيب النزول')
        doc.add_paragraph()

    # ================= 2. الجداول الإحصائية (دعم المقارنة) =================
    if stats_data:
        table_title = doc.add_paragraph()
        make_rtl(table_title)
        t_run = table_title.add_run(f"{RLM}2. الجداول الإحصائية التحليلية:{RLM}")
        t_run.font.size = Pt(14)
        t_run.font.bold = True
        t_run.font.color.rgb = RGBColor(27, 94, 32)
        set_run_rtl(t_run)

        def add_stats_table(sort_key, title_text):
            selected_data1 = stats_data.get(sort_key, {})
            selected_data2 = stats_data2.get(sort_key, {}) if stats_data2 else None
            
            labels = selected_data1.get('labels', [])
            counts1 = selected_data1.get('counts', [])
            counts2 = selected_data2.get('counts', []) if selected_data2 else []
            total1 = sum(counts1)
            
            if total1 == 0 and (not counts2 or sum(counts2) == 0): return
                
            p_st = doc.add_paragraph()
            make_rtl(p_st)
            r_st = p_st.add_run(f"{RLM}- {title_text}:{RLM}")
            r_st.font.bold = True
            set_run_rtl(r_st)
            
            table = doc.add_table(rows=1, cols=3)
            table.style = 'Table Grid'
            tblPr = table._tbl.tblPr
            bidiVisual = OxmlElement('w:bidiVisual')
            tblPr.append(bidiVisual)

            hdr_cells = table.rows[0].cells
            headers = ['القسم', query, query2] if stats_data2 else ['القسم', 'عدد الآيات', 'النسبة المئوية']
                
            for i, text in enumerate(headers):
                p = hdr_cells[i].paragraphs[0]
                make_rtl(p)
                run = p.add_run(RLM + text + RLM)
                run.font.size = Pt(12)
                run.font.bold = True
                set_run_rtl(run)

            for idx, label in enumerate(labels):
                c1 = counts1[idx]
                c2 = counts2[idx] if counts2 else 0
                if c1 > 0 or c2 > 0:
                    row_cells = table.add_row().cells
                    if stats_data2:
                        row_data = [label, str(c1), str(c2)]
                    else:
                        percent = round((c1 / total1) * 100, 1) if total1 > 0 else 0
                        row_data = [label, str(c1), f"{percent}%"]
                    
                    for i, text in enumerate(row_data):
                        p = row_cells[i].paragraphs[0]
                        make_rtl(p)
                        run = p.add_run(RLM + str(text) + RLM)
                        run.font.size = Pt(12)
                        set_run_rtl(run)
            doc.add_paragraph()

        add_stats_table('mushaf', 'توزيع الكلمة حسب ترتيب المصحف')
        add_stats_table('revelation', 'توزيع الكلمة حسب ترتيب النزول')

    # ================= 3. لوحة الإعراب والتلازم (يتم إخفاؤها في المقارنة عادة ولكن نحتفظ بها إن وجدت) =================
    if not query2: # نعرضها فقط في البحث المفرد لتجنب التداخل
        if grammar_data and (grammar_data.get('nouns', {}).get('total', 0) > 0 or grammar_data.get('verbs', {}).get('total', 0) > 0):
            p_gr_title = doc.add_paragraph()
            make_rtl(p_gr_title)
            r_gr_title = p_gr_title.add_run(f"{RLM}3. لوحة التحليل النحوي والصرفي:{RLM}")
            r_gr_title.font.bold = True
            r_gr_title.font.size = Pt(14)
            r_gr_title.font.color.rgb = RGBColor(27, 94, 32)
            set_run_rtl(r_gr_title)

            def add_grammar_section(cat_key, title_text):
                cat = grammar_data.get(cat_key, {})
                if cat.get('total', 0) > 0:
                    p_cat = doc.add_paragraph()
                    make_rtl(p_cat)
                    r_cat = p_cat.add_run(f"{RLM}- {title_text} (المجموع: {cat['total']}):{RLM}")
                    r_cat.font.bold = True
                    set_run_rtl(r_cat)
                    for item in cat.get('details', []):
                        p_item = doc.add_paragraph()
                        make_rtl(p_item)
                        r_item = p_item.add_run(f"{RLM}   * {item['name']}: {item['count']} مرات ({item['percent']}%){RLM}")
                        set_run_rtl(r_item)

            add_grammar_section('nouns', 'الأسماء')
            add_grammar_section('verbs', 'الأفعال')
            doc.add_paragraph()

        if collocations and (collocations.get('before') or collocations.get('after')):
            p_col_title = doc.add_paragraph()
            make_rtl(p_col_title)
            r_col_title = p_col_title.add_run(f"{RLM}4. الألفاظ المصاحبة (السياق):{RLM}")
            r_col_title.font.bold = True
            r_col_title.font.size = Pt(14)
            r_col_title.font.color.rgb = RGBColor(27, 94, 32)
            set_run_rtl(r_col_title)

            def add_col_section(cat_key, title_text):
                cat_list = collocations.get(cat_key, [])
                if cat_list:
                    p_cat = doc.add_paragraph()
                    make_rtl(p_cat)
                    r_cat = p_cat.add_run(f"{RLM}- {title_text}:{RLM}")
                    r_cat.font.bold = True
                    set_run_rtl(r_cat)
                    for item in cat_list:
                        p_item = doc.add_paragraph()
                        make_rtl(p_item)
                        r_item = p_item.add_run(f"{RLM}   * {item['word']}: {item['count']} مرات ({item['percent']}%){RLM}")
                        set_run_rtl(r_item)

            add_col_section('before', 'الكلمات/العبارات قبلها')
            add_col_section('after', 'الكلمات/العبارات بعدها')
            doc.add_paragraph()

    # ================= 5. الآيات والملاحظات البحثية =================
    p_aya_title = doc.add_paragraph()
    make_rtl(p_aya_title)
    r_aya_title = p_aya_title.add_run(f"{RLM}5. الآيات المستخرجة وملاحظات الباحث:{RLM}")
    r_aya_title.font.bold = True
    r_aya_title.font.size = Pt(14)
    r_aya_title.font.color.rgb = RGBColor(27, 94, 32)
    set_run_rtl(r_aya_title)

    for idx, item in enumerate(results, 1):
        p = doc.add_paragraph()
        make_rtl(p)
        run_num = p.add_run(f'{RLM}{idx}. {RLM}')
        run_num.font.bold = True
        run_num.font.size = Pt(14)
        set_run_rtl(run_num)

        text_to_show = item[display_type]
        run_aya = p.add_run(f"{RLM}﴿ {text_to_show} ﴾{RLM} ")
        run_aya.font.size = Pt(16)
        run_aya.font.name = 'Traditional Arabic'
        set_run_rtl(run_aya, cs_font='Traditional Arabic')

        run_ref = p.add_run(f"{RLM}[{item['sura_name']}:{item['aya_num']}]{RLM}")
        run_ref.font.bold = True
        run_ref.font.size = Pt(12)
        run_ref.font.color.rgb = RGBColor(100, 100, 100)
        set_run_rtl(run_ref)
        
        aya_id = str(item['id'])
        if aya_id in notes and notes[aya_id].strip():
            p_note = doc.add_paragraph()
            make_rtl(p_note)
            run_note = p_note.add_run(f"{RLM}📌 ملاحظة: {notes[aya_id].strip()}{RLM}")
            run_note.font.color.rgb = RGBColor(197, 155, 39)
            run_note.italic = True
            run_note.font.size = Pt(12)
            set_run_rtl(run_note)

    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    return file_stream