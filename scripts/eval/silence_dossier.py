# -*- coding: utf-8 -*-
"""ملفُّ عيْنٍ لتشخيص الصمت والخطأ الواثق — صورٌ تُرى لا أوصافٌ تُقرأ.

يُخرج لكلّ صفحةٍ صامتةٍ أو واثقةٍ‑مخطئة في e2e-C:
  · قصاصةَ صندوق det2 إن أطلق (وهي ما رآه القارئ فعلاً)
  · شريطَ الترويسة كاملاً (أعلى 30% من الصفحة) ليُرى أين يقع العددُ حقّاً
  · صفّاً في مانيفستٍ فيه: الحقيقة · ما قُرئ · الثقة · مصدرُ الصندوق
"""
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from PIL import Image, ImageDraw  # noqa: E402
from core.extraction.handwriting.detector import detect_boxes  # noqa: E402
from core.models import Book  # noqa: E402

RESULTS = r'D:\migration\lettersys_models\e2e_C_results.json'
OLD = r'D:\migration\lettersys_models\e2e_C_results_det1.json'
OUT = r'D:\migration\lettersys_models\silence_dossier'
os.makedirs(OUT, exist_ok=True)

_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def norm(v):
    return ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())


def render(path):
    if path.lower().endswith('.pdf'):
        import fitz
        doc = fitz.open(path)
        try:
            page = doc[0]
            z = 175 / 72.0
            lo = max(page.rect.width, page.rect.height) * z
            if lo > 3500:
                z *= 3500 / lo
            px = page.get_pixmap(matrix=fitz.Matrix(z, z))
            return Image.frombytes('RGB', (px.width, px.height), px.samples)
        finally:
            doc.close()
    return Image.open(path).convert('RGB')


rows = json.load(open(RESULTS, encoding='utf-8'))
old = {r['book']: r for r in json.load(open(OLD, encoding='utf-8'))}
DEAD = ('failed', 'pending')
scored = [r for r in rows if r.get('truth') and (r.get('status') or '') not in DEAD]

silent = [r for r in scored if not r.get('pred')]
cwrong = [r for r in scored if r.get('pred') and not r.get('hit') and r.get('conf', 0) >= 0.90]
wrong = [r for r in scored if r.get('pred') and not r.get('hit') and r.get('conf', 0) < 0.90]
print('صامت %d · واثقٌ‑ومخطئ %d · مخطئٌ دون العتبة %d' % (len(silent), len(cwrong), len(wrong)))

man = []
for kind, group in (('silent', silent), ('confident_wrong', cwrong), ('wrong', wrong)):
    for r in group:
        bid = r['book']
        rec = {'kind': kind, 'book': bid, 'truth': r.get('truth'),
               'pred': r.get('pred') or '', 'conf': r.get('conf'),
               'box_src': r.get('box_src') or '', 'status': r.get('status') or ''}
        o = old.get(bid, {})
        rec['old_pred'] = o.get('pred') or ''
        rec['old_hit'] = bool(o.get('hit'))
        try:
            b = Book.objects.get(id=bid)
            att = b.attachments.first()
            im = render(att.file.path)
            W, H = im.size
            d = detect_boxes(im)
            n = d.get('number')
            rec['det_fired'] = n is not None
            rec['det_conf'] = round(n[1], 3) if n else None

            # شريطُ الترويسة — أين يقع العددُ حقّاً
            head = im.crop((0, 0, W, int(H * 0.30)))
            if n:
                dr = ImageDraw.Draw(head)
                x0, y0, x1, y1 = n[0]
                dr.rectangle([x0 * W, y0 * H, x1 * W, y1 * H],
                             outline=(200, 30, 40), width=5)
            if head.width > 1400:
                rr = 1400 / head.width
                head = head.resize((1400, int(head.height * rr)))
            hp = os.path.join(OUT, '%s_%d_head.jpg' % (kind, bid))
            head.convert('RGB').save(hp, 'JPEG', quality=80)
            rec['head'] = os.path.basename(hp)

            if n:
                x0, y0, x1, y1 = n[0]
                crop = im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
                cp = os.path.join(OUT, '%s_%d_box.png' % (kind, bid))
                crop.save(cp)
                rec['box_img'] = os.path.basename(cp)
            del im
        except Exception as exc:
            rec['err'] = type(exc).__name__
        man.append(rec)
        print('  %-16s %-6s حقيقة %-8s قرأ %-8s' % (kind, bid, rec['truth'], rec['pred'] or '—'),
              flush=True)

json.dump(man, open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('\nحُفظ %d صفّاً ⟵ %s' % (len(man), OUT))
