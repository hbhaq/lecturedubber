"""Conservative text-only notes PDF: no invented typesetting of equations."""
from pathlib import Path
from xml.sax.saxutils import escape
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
def notes_pdf(path,markdown):
    font='Helvetica';glyphs=None
    for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/arial.ttf'):
        if Path(candidate).exists():
            pdfmetrics.registerFont(TTFont('NotesUnicode',candidate));font='NotesUnicode';glyphs=pdfmetrics.getFont(font).face.charToGlyph;break
    styles=getSampleStyleSheet()
    for style in styles.byName.values(): style.fontName=font
    styles['BodyText'].leading=16
    flow=[]
    for line in markdown.splitlines():
        if not line.strip(): continue
        missing=[c for c in line if ord(c)>127 and glyphs is not None and ord(c) not in glyphs]
        for c in missing: line=line.replace(c,f'[U+{ord(c):04X}; see Markdown]')
        style=styles['Heading1'] if line.startswith('# ') else styles['Heading2'] if line.startswith('## ') else styles['BodyText']
        text=escape(line.lstrip('# ').replace('**',''))
        match=re.fullmatch(r'\[([^\]]+)\]\((lecture.mp4#t=[0-9.]+)\)',line)
        if match: text=f'<link href="{escape(match[2])}" color="#226653">{escape(match[1])}</link>'
        flow.extend([Paragraph(text,style),Spacer(1,8)])
    def footer(canvas,doc):
        canvas.setFont(font,8);canvas.setFillColorRGB(.45,.5,.45)
        canvas.drawString(48,30,'Lecture Studio | Notes from reviewed lecture content')
        canvas.drawRightString(doc.pagesize[0]-48,30,str(doc.page))
    SimpleDocTemplate(str(path),leftMargin=48,rightMargin=48,topMargin=48,bottomMargin=48,title='Lecture notes').build(flow,onFirstPage=footer,onLaterPages=footer)
