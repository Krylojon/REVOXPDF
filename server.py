from flask import Flask, request, send_file, jsonify
from io import BytesIO
import os, zipfile, json
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from PIL import Image, ImageOps

app = Flask(__name__, static_folder='static', static_url_path='')


def send_bytes(data, filename, mimetype='application/octet-stream'):
    bio = BytesIO(data); bio.seek(0)
    r = send_file(bio, download_name=filename, as_attachment=True, mimetype=mimetype)
    r.headers['X-Filename'] = filename
    return r


def parse_pages(s, n):
    if not s: return list(range(1, n + 1))
    out=[]
    for part in s.split(','):
        part=part.strip()
        if not part: continue
        if '-' in part:
            a,b=map(int, part.split('-',1)); out.extend(range(a,b+1))
        else: out.append(int(part))
    return [x for x in out if 1 <= x <= n]


def write_pdf(writer, name='revox.pdf'):
    out=BytesIO(); writer.write(out)
    return send_bytes(out.getvalue(), name, 'application/pdf')


def password_for(reader):
    if not reader.is_encrypted: return True
    pw=request.form.get('password','')
    return bool(pw and reader.decrypt(pw))


@app.get('/api/health')
def health():
    return jsonify(ok=True, app='REVOX PDF', version='FINAL')


@app.post('/api/process')
def process():
    tool=request.form.get('tool','')
    fs=request.files.getlist('files')
    if tool in ('pdf_info',) and not fs: return 'PDF tanlang',400
    if tool not in ('pdf_info',) and not fs: return 'Fayl tanlang',400
    try:
        # ---------- PDF -> operations ----------
        if tool == 'merge':
            w=PdfWriter()
            for f in fs:
                r=PdfReader(f.stream)
                if r.is_encrypted and not password_for(r): return 'PDF parolini kiriting.',400
                for p in r.pages: w.add_page(p)
            return write_pdf(w,'revox-merged.pdf')

        if tool in ('split','remove','organize','rotate','watermark','pagenumbers','protect','unlock','compress','repair','grayscale'):
            raw=fs[0].read(); r=PdfReader(BytesIO(raw))
            if r.is_encrypted:
                if not password_for(r): return 'PDF paroli noto‘g‘ri yoki kiritilmagan.',400
            w=PdfWriter(); n=len(r.pages)

            if tool=='split':
                for i in parse_pages(request.form.get('pages'),n): w.add_page(r.pages[i-1])
                return write_pdf(w,'revox-split.pdf')

            if tool=='remove':
                rem=set(parse_pages(request.form.get('pages'),n))
                for i,p in enumerate(r.pages,1):
                    if i not in rem: w.add_page(p)
                return write_pdf(w,'revox-pages-removed.pdf')

            if tool=='organize':
                order=parse_pages(request.form.get('order'),n)
                if not order: return 'Yangi tartib kiriting. Masalan: 3,1,2',400
                for i in order: w.add_page(r.pages[i-1])
                return write_pdf(w,'revox-organized.pdf')

            if tool=='rotate':
                a=int(request.form.get('angle','90'))%360
                for p in r.pages:
                    if a: p.rotate(a)
                    w.add_page(p)
                return write_pdf(w,'revox-rotated.pdf')

            if tool=='watermark':
                text=request.form.get('watermark','REVOX PDF') or 'REVOX PDF'
                for p in r.pages:
                    wm=BytesIO(); c=canvas.Canvas(wm,pagesize=(float(p.mediabox.width),float(p.mediabox.height)))
                    c.setFont('Helvetica-Bold',28); c.setFillColor(colors.Color(0.9,0.03,0.04,alpha=0.18))
                    c.saveState(); c.translate(float(p.mediabox.width)/2,float(p.mediabox.height)/2); c.rotate(35)
                    c.drawCentredString(0,0,text); c.restoreState(); c.save(); wm.seek(0)
                    p.merge_page(PdfReader(wm).pages[0]); w.add_page(p)
                return write_pdf(w,'revox-watermarked.pdf')

            if tool=='pagenumbers':
                start=int(request.form.get('start','1'))
                for idx,p in enumerate(r.pages,start):
                    ov=BytesIO(); c=canvas.Canvas(ov,pagesize=(float(p.mediabox.width),float(p.mediabox.height)))
                    c.setFont('Helvetica',10); c.setFillColor(colors.HexColor('#333333'))
                    c.drawCentredString(float(p.mediabox.width)/2,18,str(idx)); c.save(); ov.seek(0)
                    p.merge_page(PdfReader(ov).pages[0]); w.add_page(p)
                return write_pdf(w,'revox-numbered.pdf')

            if tool=='protect':
                pw=request.form.get('password','')
                if not pw: return 'Parol kiriting.',400
                for p in r.pages: w.add_page(p)
                w.encrypt(pw); return write_pdf(w,'revox-protected.pdf')

            if tool=='unlock':
                for p in r.pages: w.add_page(p)
                return write_pdf(w,'revox-unlocked.pdf')

            if tool=='compress':
                for p in r.pages:
                    try: p.compress_content_streams()
                    except Exception: pass
                    w.add_page(p)
                out=BytesIO(); w.write(out); data=out.getvalue()
                try:
                    import fitz
                    doc=fitz.open(stream=data,filetype='pdf'); compact=BytesIO()
                    doc.save(compact,garbage=4,deflate=True,clean=True); data=compact.getvalue(); doc.close()
                except Exception: pass
                return send_bytes(data,'revox-compressed.pdf','application/pdf')

            if tool=='grayscale':
                import fitz
                doc=fitz.open(stream=raw,filetype='pdf'); out=BytesIO()
                new=fitz.open()
                for page in doc:
                    pix=page.get_pixmap(colorspace=fitz.csGRAY,alpha=False)
                    p=new.new_page(width=page.rect.width,height=page.rect.height)
                    p.insert_image(page.rect,stream=pix.tobytes('png'))
                new.save(out,deflate=True); new.close(); doc.close()
                return send_bytes(out.getvalue(),'revox-grayscale.pdf','application/pdf')

            # repair = clean re-write
            for p in r.pages: w.add_page(p)
            return write_pdf(w,'revox-repaired.pdf')

        if tool=='jpg2pdf':
            imgs=[]
            for f in fs:
                im=ImageOps.exif_transpose(Image.open(f.stream)).convert('RGB')
                imgs.append(im)
            if not imgs: return 'Rasm tanlang',400
            out=BytesIO(); imgs[0].save(out,format='PDF',save_all=True,append_images=imgs[1:])
            for im in imgs: im.close()
            return send_bytes(out.getvalue(),'revox-images.pdf','application/pdf')

        if tool=='pdf2jpg' or tool=='pdf2png':
            import fitz
            doc=fitz.open(stream=fs[0].read(),filetype='pdf'); z=BytesIO()
            ext='jpg' if tool=='pdf2jpg' else 'png'
            with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zz:
                for i,p in enumerate(doc):
                    pix=p.get_pixmap(matrix=fitz.Matrix(1.8,1.8),alpha=False)
                    zz.writestr(f'page-{i+1}.{ext}',pix.tobytes(ext))
            doc.close(); return send_bytes(z.getvalue(),f'revox-pages-{ext}.zip','application/zip')

        if tool=='pdf2text':
            r=PdfReader(fs[0].stream)
            if r.is_encrypted and not password_for(r): return 'PDF parolini kiriting.',400
            txt='\n\n'.join(f'--- Page {i} ---\n{p.extract_text() or ""}' for i,p in enumerate(r.pages,1))
            return send_bytes(txt.encode('utf-8'),'revox-text.txt','text/plain')

        if tool=='word2pdf':
            from docx import Document
            doc=Document(fs[0].stream); out=BytesIO(); c=canvas.Canvas(out,pagesize=A4)
            width,height=A4; left=48; y=height-55
            c.setTitle('REVOX PDF')
            for para in doc.paragraphs:
                txt=para.text.strip()
                if not txt: y-=12; continue
                size=16 if para.style and 'Heading' in para.style.name else 12
                bold=any(run.bold for run in para.runs)
                c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
                line=''; maxw=width-96
                for word in txt.split():
                    test=(line+' '+word).strip()
                    if c.stringWidth(test,c._fontname,size)>maxw and line:
                        c.drawString(left,y,line); y-=size+7; line=word
                        if y<55: c.showPage(); y=height-55; c.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
                    else: line=test
                if line: c.drawString(left,y,line); y-=size+9
                if y<55: c.showPage(); y=height-55
            c.save(); return send_bytes(out.getvalue(),'revox-word.pdf','application/pdf')

        if tool=='pdf_info':
            r=PdfReader(fs[0].stream)
            info={
                'pages':len(r.pages), 'encrypted':bool(r.is_encrypted),
                'title':str((r.metadata or {}).title or ''),
                'author':str((r.metadata or {}).author or ''),
                'subject':str((r.metadata or {}).subject or ''),
                'creator':str((r.metadata or {}).creator or ''),
            }
            return jsonify(info)

        if tool=='extract_images':
            import fitz
            doc=fitz.open(stream=fs[0].read(),filetype='pdf'); z=BytesIO(); count=0
            with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as zz:
                for pi,p in enumerate(doc):
                    for ii,img in enumerate(p.get_images(full=True)):
                        xref=img[0]; data=doc.extract_image(xref)
                        zz.writestr(f'page-{pi+1}-image-{ii+1}.{data["ext"]}',data['image']); count+=1
            doc.close()
            if count==0: return 'PDF ichida ajratiladigan rasm topilmadi.',400
            return send_bytes(z.getvalue(),'revox-images.zip','application/zip')

        return 'Bu funksiya topilmadi.',400
    except Exception as e:
        return f'REVOX PDF xatosi: {e}',500


@app.get('/')
def home(): return app.send_static_file('index.html')

if __name__=='__main__':
    app.run(host='127.0.0.1',port=8000,debug=False)
