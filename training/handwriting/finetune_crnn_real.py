# -*- coding: utf-8 -*-
"""صقل CRNN على شرائط الأرقام الحقيقية (مرحلة 2ب) — يعمل على Kaggle GPU.

يهيّئ من أوزان v4 (crnn_weights.pt، تدريب صناعي 95.1%) ويصقل بخلطٍ
50% شرائط حقيقية منقّاة (حصاد LetterSys عبر refine_strips) + 50% صناعي
(يمنع النسيان الكارثي). التقييم الأول على شرائط حقيقية محجوزة بفصل كتب
(hash(book_id))، والثانوي على كتّاب MADBase Test (رقيب النسيان).

مصادر الداتا في كاغل: mloey1/ahdd1 + oddrationale/mnist-in-csv +
abdualrhmanahmed/lettersys-real-number-strips (خاص: strips + labels_clean.csv
+ crnn_weights.pt). المخرَج: أفضل ONNX بحسب دقة الحقيقي + metrics.json."""
import csv
import glob
import hashlib
import json
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFilter

SEED = 20260709
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
OUT = '/kaggle/working' if os.path.isdir('/kaggle/working') else '.'

CHARSET = '0123456789'
BLANK = 0
NUM_CLASSES = len(CHARSET) + 1
LEN_DIST = {1: 0.01, 2: 0.11, 3: 0.38, 4: 0.39, 5: 0.09, 6: 0.02}
STRIP_H, MAX_W = 64, 512

# ═══ 1) الشرائط الحقيقية ═══
def _find(pattern):
    hits = sorted(glob.glob(pattern, recursive=True))
    if not hits:
        raise FileNotFoundError(pattern)
    return hits[0]

REAL_CSV = _find('/kaggle/input/**/labels_clean.csv')
# محايد للتخطيط: PNGs مباشرة، أو strips.zip يُفكّ إلى مجلد العمل (التعبئة
# المضغوطة تختصر الرفع لملف واحد — درس معارك رفع 1,186 ملفاً عبر شبكة متقطعة).
try:
    REAL_DIR = os.path.dirname(_find('/kaggle/input/**/*.png'))
except FileNotFoundError:
    import zipfile
    zpath = _find('/kaggle/input/**/strips*.zip')
    REAL_DIR = '/kaggle/working/strips_refined'
    os.makedirs(REAL_DIR, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(REAL_DIR)
    print(f'فُكّ {zpath} → {REAL_DIR}')
rows = list(csv.DictReader(open(REAL_CSV, encoding='utf-8')))
rows = [r for r in rows if os.path.exists(os.path.join(REAL_DIR, r['file']))]

# فصل كتب حتمي: 15% تحقّق (فئات A/B الموثوقة فقط — C للتدريب لا للحكم)
def _is_val(r):
    h = int(hashlib.md5(r['book_id'].encode()).hexdigest(), 16) % 100
    return h < 15 and r['tier'] in ('A', 'B')

REAL_VAL = [r for r in rows if _is_val(r)]
REAL_TRAIN = [r for r in rows if not _is_val(r)]
print(f'حقيقي: تدريب={len(REAL_TRAIN)} (A/B/C) | تحقّق={len(REAL_VAL)} (A/B، كتب محجوزة)')

def load_real(r):
    """شريط حقيقي: حبر داكن على ورق فاتح → داخلياً حبر أبيض على أسود (عقد v4)."""
    img = Image.open(os.path.join(REAL_DIR, r['file'])).convert('L')
    return img, r['label']

def augment_real(img):
    """تعويم واقعي خفيف — الشرائط الحقيقية قليلة فنكثّرها دون تشويه هويتها."""
    if random.random() < 0.5:
        img = img.rotate(random.uniform(-2.5, 2.5), fillcolor=255, expand=False)
    if random.random() < 0.4:                       # قصّ/حشو أفقي طفيف
        w, h = img.size
        dx0, dx1 = random.randint(0, w // 12), random.randint(0, w // 12)
        img = img.crop((dx0, 0, w - dx1, h))
    if random.random() < 0.35:
        arr = np.asarray(img, dtype=np.float32)
        arr = arr * random.uniform(0.8, 1.15) + random.uniform(-15, 15)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if random.random() < 0.25:
        img = img.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 0.9)))
    return img

def real_to_internal(img):
    """قلب إلى نمط التدريب الداخلي (حبر أبيض) + ملاءمة الارتفاع."""
    w, h = img.size
    nw = max(32, min(MAX_W, int(w * STRIP_H / max(1, h))))
    img = img.resize((nw, STRIP_H), Image.BILINEAR)
    return Image.fromarray(255 - np.asarray(img, dtype=np.uint8))

# ═══ 2) الصناعي (مطابق لـ v4 حرفياً — رقيب النسيان ومكمّل التنوع) ═══
def _load_csv_pair(images_glob, labels_glob):
    X = np.loadtxt(_find(images_glob), delimiter=',', dtype=np.uint8).reshape(-1, 28, 28)
    y = np.loadtxt(_find(labels_glob), delimiter=',', dtype=np.int64).reshape(-1)
    return np.transpose(X, (0, 2, 1)), y

TRAIN_X, TRAIN_Y = _load_csv_pair('/kaggle/input/**/*TrainImages*.csv', '/kaggle/input/**/*TrainLabel*.csv')
TEST_X, TEST_Y = _load_csv_pair('/kaggle/input/**/*TestImages*.csv', '/kaggle/input/**/*TestLabel*.csv')

def _load_mnist_csv(pattern):
    data = np.loadtxt(_find(pattern), delimiter=',', skiprows=1, dtype=np.uint8)
    return data[:, 1:].reshape(-1, 28, 28), data[:, 0].astype(np.int64)

EN_TRAIN_X, EN_TRAIN_Y = _load_mnist_csv('/kaggle/input/**/mnist_train.csv')
EN_TEST_X, EN_TEST_Y = _load_mnist_csv('/kaggle/input/**/mnist_test.csv')

def _index_by_digit(X, y):
    return {d: np.where(y == d)[0] for d in range(10)}

POOLS_TRAIN = {'ar': (TRAIN_X, _index_by_digit(TRAIN_X, TRAIN_Y)),
               'en': (EN_TRAIN_X, _index_by_digit(EN_TRAIN_X, EN_TRAIN_Y))}
POOLS_TEST = {'ar': (TEST_X, _index_by_digit(TEST_X, TEST_Y)),
              'en': (EN_TEST_X, _index_by_digit(EN_TEST_X, EN_TEST_Y))}

def _rand_len():
    r, acc = random.random(), 0.0
    for L, p in LEN_DIST.items():
        acc += p
        if r <= acc:
            return L
    return 4

def _digit_img(X, idx_map, d):
    arr = X[random.choice(idx_map[d])]
    img = Image.fromarray(arr)
    s = random.randint(34, 54)
    img = img.resize((s, s), Image.BILINEAR)
    if random.random() < 0.4:
        shear = random.uniform(-0.25, 0.25)
        img = img.transform(img.size, Image.AFFINE, (1, shear, 0, 0, 1, 0), resample=Image.BILINEAR)
    if random.random() < 0.12:
        f = ImageFilter.MaxFilter(3) if random.random() < 0.5 else ImageFilter.MinFilter(3)
        img = img.filter(f)
    return img

def synth_strip(pools):
    L = _rand_len()
    digits = [random.randint(1, 9)] + [random.randint(0, 9) for _ in range(L - 1)]
    r = random.random()
    script = 'ar' if r < 0.50 else ('en' if r < 0.90 else 'mix')
    canvas = Image.new('L', (MAX_W, STRIP_H), 0)
    x = random.randint(4, 30)
    for d in digits:
        X, idx_map = pools[script] if script != 'mix' else pools[random.choice(('ar', 'en'))]
        g = _digit_img(X, idx_map, d)
        y = random.randint(0, max(0, STRIP_H - g.size[1]))
        canvas.paste(g, (x, y), g.point(lambda p: 255 if p > 30 else 0))
        x += g.size[0] + random.randint(-6, 10)
        if x >= MAX_W - 60:
            break
    w = min(MAX_W, x + random.randint(6, 30))
    strip = canvas.crop((0, 0, w, STRIP_H))
    if random.random() < 0.5:
        strip = strip.rotate(random.uniform(-3, 3), fillcolor=0, expand=False)
    draw = ImageDraw.Draw(strip)
    if random.random() < 0.35:
        yy = random.randint(STRIP_H - 12, STRIP_H - 4)
        draw.line((0, yy, strip.size[0], yy), fill=random.randint(40, 90), width=1)
    if random.random() < 0.20:
        cx, cy = random.randint(0, strip.size[0]), random.randint(0, STRIP_H)
        rr = random.randint(8, 22)
        draw.arc((cx - rr, cy - rr, cx + rr, cy + rr), 0, 360, fill=random.randint(60, 130))
    arr = np.asarray(strip, dtype=np.float32)
    arr *= random.uniform(0.55, 1.0)
    arr += np.random.normal(0, random.uniform(2, 12), arr.shape)
    strip = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if random.random() < 0.2:
        strip = strip.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 1.0)))
    return strip, ''.join(str(d) for d in digits)

def _norm(strip):
    arr = np.asarray(strip, dtype=np.float32)
    return (arr - arr.mean()) / (arr.std() + 1e-6)

# ═══ 3) داتاسِت الخلط 50/50 ═══
class MixDS(torch.utils.data.Dataset):
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n
    def __getitem__(self, _):
        if REAL_TRAIN and random.random() < 0.5:
            r = random.choice(REAL_TRAIN)
            img, txt = load_real(r)
            strip = real_to_internal(augment_real(img))
        else:
            strip, txt = synth_strip(POOLS_TRAIN)
        return _norm(strip), [CHARSET.index(c) + 1 for c in txt], txt

def collate(batch):
    ws = [b[0].shape[1] for b in batch]
    W = max(ws)
    imgs = np.zeros((len(batch), 1, STRIP_H, W), np.float32)
    for i, (a, _, _) in enumerate(batch):
        imgs[i, 0, :, :a.shape[1]] = a
    targets = torch.cat([torch.tensor(b[1]) for b in batch])
    tlens = torch.tensor([len(b[1]) for b in batch])
    return torch.from_numpy(imgs), targets, tlens, torch.tensor(ws), [b[2] for b in batch]

# ═══ 4) النموذج (بنية v4 حرفياً) + تهيئة من أوزانه ═══
class CRNN(nn.Module):
    def __init__(self):
        super().__init__()
        def blk(ci, co, pool):
            return nn.Sequential(nn.Conv2d(ci, co, 3, padding=1), nn.BatchNorm2d(co),
                                 nn.ReLU(inplace=True), nn.MaxPool2d(pool))
        self.cnn = nn.Sequential(blk(1, 32, 2), blk(32, 64, 2),
                                 blk(64, 128, (2, 1)), blk(128, 128, (2, 1)))
        self.proj = nn.Linear(128 * 4, 256)
        self.rnn = nn.LSTM(256, 128, num_layers=2, bidirectional=True, batch_first=True)
        self.head = nn.Linear(256, NUM_CLASSES)
    def forward(self, x):
        f = self.cnn(x)
        b, c, h, w = f.shape
        f = f.permute(0, 3, 1, 2).reshape(b, w, c * h)
        f = self.proj(f)
        f, _ = self.rnn(f)
        return self.head(f)

model = CRNN()
model.load_state_dict(torch.load(_find('/kaggle/input/**/crnn_weights.pt'), map_location='cpu'))
model = model.to(DEVICE)
print('هُيّئ من أوزان v4.')

def greedy_decode(logits):
    out = []
    for seq in logits.argmax(-1).cpu().numpy():
        prev, chars = BLANK, []
        for k in seq:
            if k != BLANK and k != prev:
                chars.append(CHARSET[k - 1])
            prev = k
        out.append(''.join(chars))
    return out

# ═══ 5) التقييم: الحقيقي أولاً، والصناعي رقيب نسيان ═══
def _eval_pairs(pairs):
    exact, by_len = 0, {}
    with torch.no_grad():
        for i in range(0, len(pairs), 64):
            chunk = pairs[i:i + 64]
            imgs, _, _, _, txts = collate(chunk)
            pred = greedy_decode(model(imgs.to(DEVICE)))
            for p, t in zip(pred, txts):
                d = by_len.setdefault(len(t), [0, 0])
                d[1] += 1; d[0] += int(p == t); exact += int(p == t)
    return exact / max(1, len(pairs)), {k: round(v[0] / v[1], 3) for k, v in sorted(by_len.items())}

REAL_VAL_PAIRS = []
for r in REAL_VAL:
    img, txt = load_real(r)
    REAL_VAL_PAIRS.append((_norm(real_to_internal(img)), [CHARSET.index(c) + 1 for c in txt], txt))
SYNTH_VAL = [(lambda s, t: (_norm(s), [CHARSET.index(c) + 1 for c in t], t))(*synth_strip(POOLS_TEST))
             for _ in range(1500)]

def evaluate():
    model.eval()
    real_acc, real_by_len = _eval_pairs(REAL_VAL_PAIRS)
    synth_acc, _ = _eval_pairs(SYNTH_VAL)
    model.train()
    return real_acc, real_by_len, synth_acc

# ═══ 6) الصقل ═══
BATCH, STEPS = 64, 2500
train_dl = torch.utils.data.DataLoader(MixDS(BATCH * STEPS), batch_size=BATCH,
                                       num_workers=4, collate_fn=collate,
                                       persistent_workers=True, prefetch_factor=6)
opt = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-4, total_steps=STEPS)
ctc = nn.CTCLoss(blank=BLANK, zero_infinity=True)

with open(f'{OUT}/charset.json', 'w', encoding='utf-8') as f:
    json.dump({'charset': CHARSET, 'blank': BLANK, 'strip_h': STRIP_H,
               'arabic_indic': '٠١٢٣٤٥٦٧٨٩',
               'preprocess': 'invert(255-x) → resize h=64 → standardize'}, f, ensure_ascii=False, indent=1)

onnx_path = f'{OUT}/handwritten_digits_crnn_v5.onnx'

def export_onnx():
    model.eval().cpu()
    torch.save(model.state_dict(), f'{OUT}/crnn_weights_v5.pt')
    try:
        dummy = torch.randn(1, 1, STRIP_H, 256)
        try:
            torch.onnx.export(model, dummy, onnx_path, opset_version=17, dynamo=False,
                              input_names=['image'], output_names=['logits'],
                              dynamic_axes={'image': {0: 'batch', 3: 'width'},
                                            'logits': {0: 'batch', 1: 'steps'}})
        except TypeError:
            torch.onnx.export(model, dummy, onnx_path, opset_version=17,
                              input_names=['image'], output_names=['logits'],
                              dynamic_axes={'image': {0: 'batch', 3: 'width'},
                                            'logits': {0: 'batch', 1: 'steps'}})
    except Exception as exc:
        print(f'تحذير: تصدير ONNX فشل ({type(exc).__name__}) — الأوزان .pt محفوظة')
    model.to(DEVICE).train()

r0, rl0, s0 = evaluate()
print(f'خط الأساس (v4 قبل الصقل): حقيقي={r0:.3f} حسب الطول={rl0} | صناعي={s0:.3f}')

model.train()
best = r0
for step, (imgs, targets, tlens, ws, _) in enumerate(train_dl, 1):
    logits = model(imgs.to(DEVICE))
    logp = F.log_softmax(logits, dim=-1).permute(1, 0, 2)
    in_lens = torch.full((imgs.size(0),), logits.size(1), dtype=torch.long)
    loss = ctc(logp, targets, in_lens, tlens)
    opt.zero_grad(); loss.backward()
    nn.utils.clip_grad_norm_(model.parameters(), 5.0)
    opt.step(); sched.step()
    if step % 250 == 0:
        real_acc, real_by_len, synth_acc = evaluate()
        print(f'step {step:>5} loss={loss.item():.3f} حقيقي={real_acc:.3f} '
              f'{real_by_len} | صناعي={synth_acc:.3f}')
        if real_acc > best:
            best = real_acc
            export_onnx()
            with open(f'{OUT}/metrics.json', 'w', encoding='utf-8') as f:
                json.dump({'real_exact': real_acc, 'real_by_length': real_by_len,
                           'synth_exact': synth_acc, 'baseline_v4_real': r0,
                           'step': step, 'real_train': len(REAL_TRAIN),
                           'real_val': len(REAL_VAL)}, f, ensure_ascii=False, indent=1)
    if step >= STEPS:
        break

real_acc, real_by_len, synth_acc = evaluate()
print(f'\nالنهاية: حقيقي={real_acc:.3f} (أساس v4: {r0:.3f}) | صناعي={synth_acc:.3f}')
if real_acc >= best:
    export_onnx()
    with open(f'{OUT}/metrics.json', 'w', encoding='utf-8') as f:
        json.dump({'real_exact': real_acc, 'real_by_length': real_by_len,
                   'synth_exact': synth_acc, 'baseline_v4_real': r0,
                   'step': STEPS, 'real_train': len(REAL_TRAIN),
                   'real_val': len(REAL_VAL)}, f, ensure_ascii=False, indent=1)
print('اكتمل — نزّل: handwritten_digits_crnn_v5.onnx + crnn_weights_v5.pt + metrics.json')
