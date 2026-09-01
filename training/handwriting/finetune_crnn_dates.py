# -*- coding: utf-8 -*-
"""v6: صقل CRNN على التواريخ اليدوية — مفردات موسّعة بالفاصل «/» (كاغل GPU).

الوراثة بلا خسارة (سياسة المالك المعلنة): تُحمَّل أوزان v5 كاملةً ما عدا طبقة
الرأس التي تتّسع لصنف الفاصل الجديد — تُنسَخ أوزان الأصناف القديمة إليها ويُهيَّأ
الصنف الجديد وحده. الخلطة الثلاثية تمنع النسيان: تواريخ حقيقية + أرقام حقيقية
+ توليد اصطناعي (تواريخ وأرقام مركّبة من MADBase/MNIST).

التقييم مزدوج ويحكم الأول: تواريخ حقيقية محجوزة بفصل كتب (hash%100<15، فئة A)،
وحارس نسيان على أرقام حقيقية محجوزة (يجب ألا ينهار عن ≈94.5%).

مصادر كاغل: mloey1/ahdd1 + oddrationale/mnist-in-csv +
abdualrhmanahmed/lettersys-real-number-strips (يحوي strips.zip الأرقام) +
abdualrhmanahmed/lettersys-real-date-strips (dates.zip + labels_date_clean.csv
+ crnn_weights_v5.pt).
"""
import csv
import glob
import hashlib
import json
import os
import random
import zipfile

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFilter

SEED = 20260713
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
OUT = '/kaggle/working' if os.path.isdir('/kaggle/working') else '.'

# ── المفردات: أرقام + الفاصل. الترتيب حرج: الأرقام تحتفظ بفهارسها من v5
#    (فهرس CTC = موضع المحرف + 1) فتُنقل أوزان رأسها كما هي، والفاصل يذيّلها.
OLD_CHARSET = '0123456789'
CHARSET = OLD_CHARSET + '/'
BLANK = 0
NUM_CLASSES = len(CHARSET) + 1
STRIP_H, MAX_W = 64, 512


def _find(pattern):
    hits = sorted(glob.glob(pattern, recursive=True))
    if not hits:
        raise FileNotFoundError(pattern)
    return hits[0]


def _unzip_or_dir(zip_glob, png_glob, workdir):
    """يعيد مجلد الصور: إمّا PNGs جاهزة أو يفكّ الأرشيف (رفع الملف الواحد)."""
    try:
        return os.path.dirname(_find(png_glob))
    except FileNotFoundError:
        z = _find(zip_glob)
        os.makedirs(workdir, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(workdir)
        print(f'فُكّ {z} → {workdir}')
        return workdir


# ═══ 1) التواريخ الحقيقية ═══
DATE_CSV = _find('/kaggle/input/**/labels_date_clean.csv')
DATE_DIR = _unzip_or_dir('/kaggle/input/**/dates*.zip',
                         os.path.join(os.path.dirname(DATE_CSV), '*.png'),
                         '/kaggle/working/dates')
date_rows = [r for r in csv.DictReader(open(DATE_CSV, encoding='utf-8'))
             if os.path.exists(os.path.join(DATE_DIR, r['file']))]


def _is_val(r, tiers=('A',)):
    h = int(hashlib.md5(r['book_id'].encode()).hexdigest(), 16) % 100
    return h < 15 and r['tier'] in tiers


DATE_VAL = [r for r in date_rows if _is_val(r)]
DATE_TRAIN = [r for r in date_rows if not _is_val(r)]
print(f'تواريخ حقيقية: تدريب={len(DATE_TRAIN)} | تحقّق={len(DATE_VAL)} (فئة A، كتب محجوزة)')

# ═══ 2) الأرقام الحقيقية (حارس النسيان + تنوّع) ═══
NUM_CSV = _find('/kaggle/input/**/labels_clean.csv')
NUM_DIR = _unzip_or_dir('/kaggle/input/**/strips*.zip',
                        os.path.join(os.path.dirname(NUM_CSV), '*.png'),
                        '/kaggle/working/nums')
num_rows = [r for r in csv.DictReader(open(NUM_CSV, encoding='utf-8'))
            if os.path.exists(os.path.join(NUM_DIR, r['file']))]
NUM_VAL = [r for r in num_rows if _is_val(r, tiers=('A', 'B'))]
NUM_TRAIN = [r for r in num_rows if not _is_val(r, tiers=('A', 'B'))]
print(f'أرقام حقيقية: تدريب={len(NUM_TRAIN)} | تحقّق={len(NUM_VAL)}')


def load_real(directory, r):
    img = Image.open(os.path.join(directory, r['file'])).convert('L')
    return img, r['label']


def augment(img):
    if random.random() < 0.5:
        img = img.rotate(random.uniform(-2.5, 2.5), fillcolor=255, expand=False)
    if random.random() < 0.4:
        w, h = img.size
        dx0, dx1 = random.randint(0, max(1, w // 14)), random.randint(0, max(1, w // 14))
        if w - dx1 > dx0 + 16:
            img = img.crop((dx0, 0, w - dx1, h))
    if random.random() < 0.35:
        a = np.asarray(img, dtype=np.float32) * random.uniform(0.8, 1.15) + random.uniform(-15, 15)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if random.random() < 0.25:
        img = img.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 0.9)))
    return img


def to_internal(img):
    """حبر داكن على ورق فاتح → نمط التدريب الداخلي (حبر أبيض) بارتفاع 64."""
    w, h = img.size
    nw = max(32, min(MAX_W, int(w * STRIP_H / max(1, h))))
    img = img.resize((nw, STRIP_H), Image.BILINEAR)
    return Image.fromarray(255 - np.asarray(img, dtype=np.uint8))


# ═══ 3) الاصطناعي: أرقام وتواريخ مركّبة (يمنع النسيان ويوسّع التنوّع) ═══
def _load_csv_pair(images_glob, labels_glob):
    X = np.loadtxt(_find(images_glob), delimiter=',', dtype=np.uint8).reshape(-1, 28, 28)
    y = np.loadtxt(_find(labels_glob), delimiter=',', dtype=np.int64).reshape(-1)
    return np.transpose(X, (0, 2, 1)), y


def _load_mnist(pattern):
    d = np.loadtxt(_find(pattern), delimiter=',', skiprows=1, dtype=np.uint8)
    return d[:, 1:].reshape(-1, 28, 28), d[:, 0].astype(np.int64)


AR_X, AR_Y = _load_csv_pair('/kaggle/input/**/*TrainImages*.csv', '/kaggle/input/**/*TrainLabel*.csv')
EN_X, EN_Y = _load_mnist('/kaggle/input/**/mnist_train.csv')
POOLS = {'ar': (AR_X, {d: np.where(AR_Y == d)[0] for d in range(10)}),
         'en': (EN_X, {d: np.where(EN_Y == d)[0] for d in range(10)})}


def _glyph(X, idx, d):
    img = Image.fromarray(X[random.choice(idx[d])])
    s = random.randint(34, 54)
    img = img.resize((s, s), Image.BILINEAR)
    if random.random() < 0.4:
        img = img.transform(img.size, Image.AFFINE,
                            (1, random.uniform(-0.25, 0.25), 0, 0, 1, 0), resample=Image.BILINEAR)
    return img


def _slash_glyph(size):
    """فاصل مرسوم يدوياً: خط مائل بميلٍ وسماكة متغيّرين (لا خطّ لدينا صورُه)."""
    g = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(g)
    lean = random.uniform(0.12, 0.34)
    d.line((size * (0.5 - lean), size * 0.92, size * (0.5 + lean), size * 0.08),
           fill=255, width=random.randint(2, 4))
    return g


def synth_strip():
    """سلسلة اصطناعية: تاريخ (بفواصل) بنسبة 55% أو رقم مجرّد."""
    script = 'ar' if random.random() < 0.55 else 'en'
    X, idx = POOLS[script]
    is_date = random.random() < 0.55
    if is_date:
        d, m = random.randint(1, 28), random.randint(1, 12)
        y = random.choice((str(random.randint(2020, 2026)), f'{random.randint(20, 26):02}'))
        pad = random.random() < 0.5
        parts = ([f'{d:02}' if pad else str(d), f'{m:02}' if pad else str(m), y]
                 if random.random() < 0.7 else [y, f'{m:02}' if pad else str(m),
                                                f'{d:02}' if pad else str(d)])
        text = '/'.join(parts)
    else:
        L = random.choice((2, 3, 3, 4, 4, 5))
        text = str(random.randint(1, 9)) + ''.join(str(random.randint(0, 9)) for _ in range(L - 1))

    canvas = Image.new('L', (MAX_W, STRIP_H), 0)
    x = random.randint(4, 24)
    for ch in text:
        g = _slash_glyph(random.randint(34, 50)) if ch == '/' else _glyph(X, idx, int(ch))
        y0 = random.randint(0, max(0, STRIP_H - g.size[1]))
        canvas.paste(g, (x, y0), g.point(lambda p: 255 if p > 30 else 0))
        x += g.size[0] + random.randint(-6, 8)
        if x >= MAX_W - 60:
            break
    strip = canvas.crop((0, 0, min(MAX_W, x + random.randint(6, 24)), STRIP_H))
    if random.random() < 0.5:
        strip = strip.rotate(random.uniform(-3, 3), fillcolor=0, expand=False)
    dr = ImageDraw.Draw(strip)
    if random.random() < 0.3:
        yy = random.randint(STRIP_H - 12, STRIP_H - 4)
        dr.line((0, yy, strip.size[0], yy), fill=random.randint(40, 90), width=1)
    a = np.asarray(strip, dtype=np.float32) * random.uniform(0.55, 1.0)
    a += np.random.normal(0, random.uniform(2, 12), a.shape)
    strip = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if random.random() < 0.2:
        strip = strip.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 1.0)))
    return strip, text


def _norm(strip):
    a = np.asarray(strip, dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


def encode(txt):
    return [CHARSET.index(c) + 1 for c in txt]


class MixDS(torch.utils.data.Dataset):
    """40% تواريخ حقيقية | 20% أرقام حقيقية | 40% اصطناعي."""
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n
    def __getitem__(self, _):
        r = random.random()
        if r < 0.40 and DATE_TRAIN:
            row = random.choice(DATE_TRAIN)
            img, txt = load_real(DATE_DIR, row)
            strip = to_internal(augment(img))
        elif r < 0.60 and NUM_TRAIN:
            row = random.choice(NUM_TRAIN)
            img, txt = load_real(NUM_DIR, row)
            strip = to_internal(augment(img))
        else:
            strip, txt = synth_strip()
        return _norm(strip), encode(txt), txt


def collate(batch):
    ws = [b[0].shape[1] for b in batch]
    W = max(ws)
    imgs = np.zeros((len(batch), 1, STRIP_H, W), np.float32)
    for i, (a, _, _) in enumerate(batch):
        imgs[i, 0, :, :a.shape[1]] = a
    targets = torch.cat([torch.tensor(b[1]) for b in batch])
    tlens = torch.tensor([len(b[1]) for b in batch])
    return torch.from_numpy(imgs), targets, tlens, torch.tensor(ws), [b[2] for b in batch]


# ═══ 4) النموذج + وراثة أوزان v5 (رأسٌ موسَّع بلا خسارة) ═══
class CRNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        def blk(ci, co, pool):
            return nn.Sequential(nn.Conv2d(ci, co, 3, padding=1), nn.BatchNorm2d(co),
                                 nn.ReLU(inplace=True), nn.MaxPool2d(pool))
        self.cnn = nn.Sequential(blk(1, 32, 2), blk(32, 64, 2),
                                 blk(64, 128, (2, 1)), blk(128, 128, (2, 1)))
        self.proj = nn.Linear(128 * 4, 256)
        self.rnn = nn.LSTM(256, 128, num_layers=2, bidirectional=True, batch_first=True)
        self.head = nn.Linear(256, num_classes)
    def forward(self, x):
        f = self.cnn(x)
        b, c, h, w = f.shape
        f = f.permute(0, 3, 1, 2).reshape(b, w, c * h)
        f = self.proj(f)
        f, _ = self.rnn(f)
        return self.head(f)


model = CRNN(NUM_CLASSES)
sd = torch.load(_find('/kaggle/input/**/crnn_weights_v5.pt'), map_location='cpu')
old_w, old_b = sd.pop('head.weight'), sd.pop('head.bias')
missing = model.load_state_dict(sd, strict=False)
with torch.no_grad():                       # فراغ CTC + الأرقام العشرة كما هي
    model.head.weight[:old_w.shape[0]] = old_w
    model.head.bias[:old_b.shape[0]] = old_b
print(f'وُرثت أوزان v5 ({old_w.shape[0]} صنفاً) — الرأس اتّسع إلى {NUM_CLASSES} '
      f'(الفاصل «/» مُهيَّأ حديثاً). مفاتيح مفقودة: {list(missing.missing_keys)}')
model = model.to(DEVICE)


def greedy(logits):
    out = []
    for seq in logits.argmax(-1).cpu().numpy():
        prev, chars = BLANK, []
        for k in seq:
            if k != BLANK and k != prev:
                chars.append(CHARSET[k - 1])
            prev = k
        out.append(''.join(chars))
    return out


def _pairs(rows, directory):
    ps = []
    for r in rows:
        img, txt = load_real(directory, r)
        ps.append((_norm(to_internal(img)), encode(txt), txt))
    return ps


DATE_VAL_P = _pairs(DATE_VAL, DATE_DIR)
NUM_VAL_P = _pairs(NUM_VAL, NUM_DIR)


def _eval(pairs, iso_ok=False):
    """دقة التطابق التام؛ ولحقل التاريخ نقيس أيضاً «التاريخ المفكوك الصحيح»
    (رقم/شهر/سنة متطابقة) لأن رسم الفاصل ليس المنتج."""
    if not pairs:
        return 0.0, 0.0
    exact = parsed = 0
    with torch.no_grad():
        for i in range(0, len(pairs), 64):
            chunk = pairs[i:i + 64]
            imgs, _, _, _, txts = collate(chunk)
            preds = greedy(model(imgs.to(DEVICE)))
            for p, t in zip(preds, txts):
                exact += int(p == t)
                if iso_ok:
                    pp = [x for x in p.split('/') if x]
                    tt = [x for x in t.split('/') if x]
                    parsed += int(len(pp) == len(tt) == 3
                                  and all(a.lstrip('0') == b.lstrip('0') for a, b in zip(pp, tt)))
    n = len(pairs)
    return exact / n, (parsed / n if iso_ok else 0.0)


def evaluate():
    model.eval()
    d_exact, d_parsed = _eval(DATE_VAL_P, iso_ok=True)
    n_exact, _ = _eval(NUM_VAL_P)
    model.train()
    return d_exact, d_parsed, n_exact


# ═══ 5) الصقل ═══
BATCH, STEPS = 64, 3000
train_dl = torch.utils.data.DataLoader(MixDS(BATCH * STEPS), batch_size=BATCH,
                                       num_workers=4, collate_fn=collate,
                                       persistent_workers=True, prefetch_factor=6)
opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-4, total_steps=STEPS)
ctc = nn.CTCLoss(blank=BLANK, zero_infinity=True)

with open(f'{OUT}/charset_v6.json', 'w', encoding='utf-8') as f:
    json.dump({'charset': CHARSET, 'blank': BLANK, 'strip_h': STRIP_H,
               'arabic_indic': '٠١٢٣٤٥٦٧٨٩',
               'preprocess': 'invert(255-x) → resize h=64 → standardize'},
              f, ensure_ascii=False, indent=1)

onnx_path = f'{OUT}/handwritten_dates_crnn_v6.onnx'


def export():
    model.eval().cpu()
    torch.save(model.state_dict(), f'{OUT}/crnn_weights_v6.pt')
    try:
        dummy = torch.randn(1, 1, STRIP_H, 256)
        torch.onnx.export(model, dummy, onnx_path, opset_version=17, dynamo=False,
                          input_names=['image'], output_names=['logits'],
                          dynamic_axes={'image': {0: 'batch', 3: 'width'},
                                        'logits': {0: 'batch', 1: 'steps'}})
    except Exception as exc:
        print(f'تحذير: تصدير ONNX فشل ({type(exc).__name__}) — الأوزان .pt محفوظة')
    model.to(DEVICE).train()


d0, p0, n0 = evaluate()
print(f'خط الأساس (v5 قبل صقل التواريخ): تاريخ تام={d0:.3f} مفكوك={p0:.3f} | أرقام={n0:.3f}')

model.train()
best = 0.0
for step, (imgs, targets, tlens, ws, _) in enumerate(train_dl, 1):
    logits = model(imgs.to(DEVICE))
    logp = F.log_softmax(logits, dim=-1).permute(1, 0, 2)
    in_lens = torch.full((imgs.size(0),), logits.size(1), dtype=torch.long)
    loss = ctc(logp, targets, in_lens, tlens)
    opt.zero_grad(); loss.backward()
    nn.utils.clip_grad_norm_(model.parameters(), 5.0)
    opt.step(); sched.step()
    if step % 250 == 0:
        d_exact, d_parsed, n_exact = evaluate()
        print(f'step {step:>5} loss={loss.item():.3f} | تاريخ تام={d_exact:.3f} '
              f'مفكوك={d_parsed:.3f} | حارس الأرقام={n_exact:.3f}')
        if d_parsed > best:                 # الحَكَم: التاريخ المفكوك الصحيح
            best = d_parsed
            export()
            with open(f'{OUT}/metrics_v6.json', 'w', encoding='utf-8') as f:
                json.dump({'date_exact': d_exact, 'date_parsed': d_parsed,
                           'number_sentinel': n_exact, 'baseline_v5_date_parsed': p0,
                           'baseline_v5_number': n0, 'step': step,
                           'date_train': len(DATE_TRAIN), 'date_val': len(DATE_VAL)},
                          f, ensure_ascii=False, indent=1)
    if step >= STEPS:
        break

d_exact, d_parsed, n_exact = evaluate()
print(f'\nالنهاية: تاريخ تام={d_exact:.3f} | مفكوك={d_parsed:.3f} (أساس {p0:.3f}) '
      f'| حارس الأرقام={n_exact:.3f} (أساس {n0:.3f})')
if d_parsed >= best:
    export()
print('اكتمل — نزّل: handwritten_dates_crnn_v6.onnx + crnn_weights_v6.pt + metrics_v6.json')
