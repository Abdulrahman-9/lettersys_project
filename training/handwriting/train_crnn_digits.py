# -*- coding: utf-8 -*-
"""تدريب CRNN-CTC لقراءة أرقام الصادر المكتوبة بخط اليد — يعمل على Kaggle GPU.

═══ كيف تشغّله (مرّة واحدة) ═══
1) kaggle.com → Create → New Notebook.
2) Add Input → ابحث «Arabic Handwritten Digits Dataset» (mloey1/ahdd1) وأضِفه.
3) Settings → Accelerator → GPU (T4).
4) الصق هذا الملف كاملاً في خلية واحدة → Run All (~45-60 دقيقة).
5) من تبويب Output نزّل: handwritten_digits_crnn.onnx + charset.json + metrics.json
   وسلّمها للدمج (مرحلة 3 في HANDWRITING_NUMBERS_PLAN_2026-07-06.md).

═══ التصميم (قرارات الخطة المحسومة) ═══
- المفردات v1: الأرقام العشرة فقط (٠-٩) — 91% من أرقام قاعدةِ بياناتنا أرقامٌ
  مجرّدة بطول 2-5؛ الفواصل (/-) تُضاف في v2 بعد إثبات الأساس.
- CTC يقرأ السلسلة كاملة بلا تقطيع (يطابق وسمنا: قيمة بلا صناديق).
- تدريبٌ اصطناعي بحت من MADBase (70 ألف رقم بخط 700 كاتب) مع محاكاة
  عيوب مسوحاتنا (ميل/تلاشي حبر/ضجيج/خطوط نماذج) — ثم ضبطٌ لاحق على
  أشرطة حقيقية بإشراف ضعيف (خارج هذا السكربت).
- فصل الكُتّاب: التدريب يركّب من أرقام Train، والتقييم من أرقام Test
  (كتّابٌ لم يرَهم النموذج) — يمنع تفاؤلاً زائفاً.
- المخرَج ONNX بعرضٍ ديناميكي — استدلال CPU خفيف على جهاز 8GB بلا PyTorch.
"""
import glob
import json
import math
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFilter

SEED = 20260706
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
OUT = '/kaggle/working' if os.path.isdir('/kaggle/working') else '.'

# ── المفردات: فهرس 0 محجوز لفراغ CTC ──
CHARSET = '0123456789'                 # داخلياً غربية؛ العرض النهائي عربي-هندي في التطبيق
BLANK = 0
NUM_CLASSES = len(CHARSET) + 1

# توزيع أطوال السلاسل — مقيسٌ من 4000 رقم مؤكَّد في قاعدة بياناتنا
LEN_DIST = {1: 0.01, 2: 0.11, 3: 0.38, 4: 0.39, 5: 0.09, 6: 0.02}

STRIP_H = 64            # ارتفاع الشريط الموحَّد (عقد المعالجة — انظر preprocess_strip)
MAX_W = 512

# ═══ 1) تحميل MADBase (أسماء الملفات تختلف بين مرايا الداتاسِت — نلتقطها بنمط) ═══
def _load_csv_pair(images_glob, labels_glob):
    imgs_path = sorted(glob.glob(images_glob, recursive=True))[0]
    lbls_path = sorted(glob.glob(labels_glob, recursive=True))[0]
    X = np.loadtxt(imgs_path, delimiter=',', dtype=np.uint8).reshape(-1, 28, 28)
    y = np.loadtxt(lbls_path, delimiter=',', dtype=np.int64).reshape(-1)
    # اتجاه صور MADBase-CSV معكوس الأصل (تخزين MNIST-style) — نصحّحه، وخلية
    # المعاينة أدناه تتيح التحقّق بالعين: إن بدت الأرقام مقلوبة اعكس القلاب.
    X = np.transpose(X, (0, 2, 1))
    return X, y

TRAIN_X, TRAIN_Y = _load_csv_pair('/kaggle/input/**/*TrainImages*.csv',
                                  '/kaggle/input/**/*TrainLabel*.csv')
TEST_X, TEST_Y = _load_csv_pair('/kaggle/input/**/*TestImages*.csv',
                                '/kaggle/input/**/*TestLabel*.csv')
print(f'MADBase (عربي-هندي): train={len(TRAIN_X)} test={len(TEST_X)}')

# v3: كتب المالك فيها أرقام لاتينية بخط اليد أيضاً (شؤون التراخيص) — نمزج MNIST.
# صيغة mnist-in-csv: صفّ = label,784 بكسل، مع سطر عناوين.
def _load_mnist_csv(pattern):
    path = sorted(glob.glob(pattern, recursive=True))[0]
    data = np.loadtxt(path, delimiter=',', skiprows=1, dtype=np.uint8)
    return data[:, 1:].reshape(-1, 28, 28), data[:, 0].astype(np.int64)

EN_TRAIN_X, EN_TRAIN_Y = _load_mnist_csv('/kaggle/input/**/mnist_train.csv')
EN_TEST_X, EN_TEST_Y = _load_mnist_csv('/kaggle/input/**/mnist_test.csv')
print(f'MNIST (لاتيني): train={len(EN_TRAIN_X)} test={len(EN_TEST_X)}')

# فهرس صور كل رقم (للتركيب السريع)
def _index_by_digit(X, y):
    return {d: np.where(y == d)[0] for d in range(10)}

TRAIN_IDX = _index_by_digit(TRAIN_X, TRAIN_Y)
TEST_IDX = _index_by_digit(TEST_X, TEST_Y)
EN_TRAIN_IDX = _index_by_digit(EN_TRAIN_X, EN_TRAIN_Y)
EN_TEST_IDX = _index_by_digit(EN_TEST_X, EN_TEST_Y)

# مجمّعات النمطين: (تدريب، اختبار) — الاختبار من كتّابٍ لم يرَهم النموذج
POOLS_TRAIN = {'ar': (TRAIN_X, TRAIN_IDX), 'en': (EN_TRAIN_X, EN_TRAIN_IDX)}
POOLS_TEST = {'ar': (TEST_X, TEST_IDX), 'en': (EN_TEST_X, EN_TEST_IDX)}

# ═══ 2) مُركِّب السلاسل الاصطناعي — يحاكي أشرطة مسوحاتنا ═══
def _rand_len():
    r, acc = random.random(), 0.0
    for L, p in LEN_DIST.items():
        acc += p
        if r <= acc:
            return L
    return 4

def _digit_img(X, idx_map, d):
    arr = X[random.choice(idx_map[d])]
    img = Image.fromarray(arr)                      # حبرٌ أبيض على أسود (نمط MNIST)
    s = random.randint(34, 54)                      # تفاوت أحجام الخط اليدوي
    img = img.resize((s, s), Image.BILINEAR)
    if random.random() < 0.4:                       # ميل الكتابة (قصّ أفيني)
        shear = random.uniform(-0.25, 0.25)
        img = img.transform(img.size, Image.AFFINE, (1, shear, 0, 0, 1, 0),
                            resample=Image.BILINEAR)
    if random.random() < 0.12:                      # سماكة/نحافة الحبر (مُخفَّف — كان عنق سرعة v1)
        f = ImageFilter.MaxFilter(3) if random.random() < 0.5 else ImageFilter.MinFilter(3)
        img = img.filter(f)
    return img

def synth_strip(pools):
    """يُعيد (صورة شريط H=64 بعرض متغيّر، نصّ السلسلة). حبرٌ أبيض على أسود داخلياً.

    v3 — نمطان للأرقام: عربي-هندي (MADBase) ولاتيني (MNIST). السلاسل أحاديةُ
    النمط غالباً (كما في الواقع: الكاتب يلتزم نمطاً) — وهذا يحلّ التباس ٥/0
    (كلاهما دائرة): سياق الجيران عبر BiLSTM يحسم النمط. 10% مختلطة للمتانة.
    الفئات موحَّدة (٤ و4 كلاهما = 4) — المخرَج قيمةٌ لا رسم."""
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
        x += g.size[0] + random.randint(-6, 10)     # تراكب/تباعد خط اليد
        if x >= MAX_W - 60:
            break
    w = min(MAX_W, x + random.randint(6, 30))
    strip = canvas.crop((0, 0, w, STRIP_H))
    # عيوب المسح: دوران خفيف، خط نموذج، بقعة ختم، تلاشٍ، ضجيج، تمويه
    if random.random() < 0.5:
        strip = strip.rotate(random.uniform(-3, 3), fillcolor=0, expand=False)
    draw = ImageDraw.Draw(strip)
    if random.random() < 0.35:                      # سطر النموذج المطبوع تحت الرقم
        yy = random.randint(STRIP_H - 12, STRIP_H - 4)
        draw.line((0, yy, strip.size[0], yy), fill=random.randint(40, 90), width=1)
    if random.random() < 0.20:                      # حافّة ختم/بقعة
        cx, cy = random.randint(0, strip.size[0]), random.randint(0, STRIP_H)
        r = random.randint(8, 22)
        draw.arc((cx - r, cy - r, cx + r, cy + r), 0, 360, fill=random.randint(60, 130))
    arr = np.asarray(strip, dtype=np.float32)
    arr *= random.uniform(0.55, 1.0)                # تلاشي الحبر (كربون/قلم باهت)
    arr += np.random.normal(0, random.uniform(2, 12), arr.shape)   # ضجيج الماسح
    strip = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if random.random() < 0.2:                       # مُخفَّف (كان عنق سرعة v1)
        strip = strip.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 1.0)))
    return strip, ''.join(str(d) for d in digits)

# عقد المعالجة للتطبيق (يُنسَخ حرفياً للاستدلال في مرحلة 3):
# المقصوصة عندنا حبرٌ داكن على ورق فاتح → اعكسها (255-x) ثم طبّق نفس التطبيع.
def preprocess_strip(pil_gray):
    w, h = pil_gray.size
    nw = max(32, min(MAX_W, int(w * STRIP_H / h)))
    img = pil_gray.resize((nw, STRIP_H), Image.BILINEAR)
    arr = 255.0 - np.asarray(img, dtype=np.float32)          # حبر أبيض داخلياً
    arr = (arr - arr.mean()) / (arr.std() + 1e-6)
    return arr[None, None]                                    # (1,1,H,W)

def _norm(strip):
    arr = np.asarray(strip, dtype=np.float32)
    return (arr - arr.mean()) / (arr.std() + 1e-6)

# ═══ 3) داتاسِت توليدي + تجميع دفعات بحشو عرض ═══
class SynthDS(torch.utils.data.Dataset):
    def __init__(self, pools, n):
        self.pools, self.n = pools, n
    def __len__(self):
        return self.n
    def __getitem__(self, _):
        s, txt = synth_strip(self.pools)
        return _norm(s), [CHARSET.index(c) + 1 for c in txt], txt

def collate(batch):
    ws = [b[0].shape[1] for b in batch]
    W = max(ws)
    imgs = np.zeros((len(batch), 1, STRIP_H, W), np.float32)
    for i, (a, _, _) in enumerate(batch):
        imgs[i, 0, :, :a.shape[1]] = a
    targets = torch.cat([torch.tensor(b[1]) for b in batch])
    tlens = torch.tensor([len(b[1]) for b in batch])
    return torch.from_numpy(imgs), targets, tlens, torch.tensor(ws), [b[2] for b in batch]

# ═══ 4) النموذج: CNN → BiLSTM → CTC ═══
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
    def forward(self, x):                    # x: (B,1,64,W)
        f = self.cnn(x)                      # (B,128,4,W/4)
        b, c, h, w = f.shape
        f = f.permute(0, 3, 1, 2).reshape(b, w, c * h)
        f = self.proj(f)
        f, _ = self.rnn(f)
        return self.head(f)                  # (B, W/4, classes)

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

# ═══ 5) التدريب ═══
# دروس v1 (أُلغيت عند سقف 12 ساعة): التوليد كان يخنق الـGPU (56د/1000 خطوة)،
# والنموذج بلغ 96.1% عند 12k أصلاً — لذا v2: توليد أخفّ + عمّال أكثر + خطوات
# أقل تكفي + **تصدير ONNX عند كل تقييم** فلا يضيع النموذج مهما حدث.
BATCH, STEPS, VAL_N = 64, 7000, 4000   # قياس v3: ~52د/1000 خطوة ⇒ ~6 ساعات (هامش مريح تحت 12)
train_dl = torch.utils.data.DataLoader(SynthDS(POOLS_TRAIN, BATCH * STEPS),
                                       batch_size=BATCH, num_workers=4, collate_fn=collate,
                                       persistent_workers=True, prefetch_factor=6)
val_set = [SynthDS(POOLS_TEST, 1)[0] for _ in range(VAL_N)]   # كتّاب Test فقط (النمطان)

model = CRNN().to(DEVICE)
opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=STEPS)
ctc = nn.CTCLoss(blank=BLANK, zero_infinity=True)

# معاينة بشرية: شبكة عيّنات — إن بدت الأرقام معكوسة فبدّل قلاب الاتجاه أعلاه
grid = Image.new('L', (MAX_W, STRIP_H * 8), 20)
for i in range(8):
    s, t = synth_strip(POOLS_TRAIN)
    grid.paste(s, (0, i * STRIP_H))
grid.save(f'{OUT}/sanity_samples.png')
print('حُفظت sanity_samples.png — تحقّق أن الأرقام تبدو طبيعية غير معكوسة.')

def evaluate():
    model.eval()
    exact = 0
    by_len = {}
    with torch.no_grad():
        for i in range(0, VAL_N, 128):
            chunk = val_set[i:i + 128]
            imgs, _, _, _, txts = collate(chunk)
            pred = greedy_decode(model(imgs.to(DEVICE)))
            for p, t in zip(pred, txts):
                d = by_len.setdefault(len(t), [0, 0])
                d[1] += 1
                d[0] += int(p == t)
                exact += int(p == t)
    model.train()
    return exact / VAL_N, {k: round(v[0] / v[1], 3) for k, v in sorted(by_len.items())}


onnx_path = f'{OUT}/handwritten_digits_crnn.onnx'

# عقد المفردات يُكتب مبكراً — يبقى موجوداً حتى لو أُلغيت الجلسة (درس v1)
with open(f'{OUT}/charset.json', 'w', encoding='utf-8') as f:
    json.dump({'charset': CHARSET, 'blank': BLANK, 'strip_h': STRIP_H,
               'arabic_indic': '٠١٢٣٤٥٦٧٨٩',
               'preprocess': 'invert(255-x) → resize h=64 → standardize (انظر preprocess_strip)'},
              f, ensure_ascii=False, indent=1)

def export_onnx():
    """تصدير قابل للاستدعاء دورياً — درس v1: الإلغاء عند سقف الجلسة أضاع نموذج 96%.
    درس v3: torch الحديث يطلب onnxscript لمسار dynamo (غير مثبَّتة والإنترنت مغلق)
    → المُصدّر التقليدي، وأي فشل تصديرٍ لا يقتل التدريب؛ الأوزان تُحفَظ دائماً."""
    model.eval().cpu()
    torch.save(model.state_dict(), f'{OUT}/crnn_weights.pt')   # احتياطي غير قابل للكسر
    try:
        dummy = torch.randn(1, 1, STRIP_H, 256)
        try:
            torch.onnx.export(model, dummy, onnx_path, opset_version=17, dynamo=False,
                              input_names=['image'], output_names=['logits'],
                              dynamic_axes={'image': {0: 'batch', 3: 'width'},
                                            'logits': {0: 'batch', 1: 'steps'}})
        except TypeError:   # إصدار torch أقدم بلا وسيط dynamo
            torch.onnx.export(model, dummy, onnx_path, opset_version=17,
                              input_names=['image'], output_names=['logits'],
                              dynamic_axes={'image': {0: 'batch', 3: 'width'},
                                            'logits': {0: 'batch', 1: 'steps'}})
    except Exception as exc:
        print(f'تحذير: تصدير ONNX فشل ({type(exc).__name__}: {exc}) — الأوزان .pt محفوظة')
    model.to(DEVICE).train()

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
    if step % 1000 == 0:
        acc, by_len = evaluate()
        print(f'step {step:>6} loss={loss.item():.3f} exact={acc:.3f} حسب الطول={by_len}')
        if acc > best:                      # نُصدّر الأفضل حتى الآن — لا خسارة بعد اليوم
            best = acc
            export_onnx()
            with open(f'{OUT}/metrics.json', 'w', encoding='utf-8') as f:
                json.dump({'exact_match': acc, 'by_length': by_len, 'step': step,
                           'val_writers': 'MADBase test split (unseen writers)'}, f, indent=1)
    if step >= STEPS:
        break

acc, by_len = evaluate()
print(f'\nالنتيجة النهائية (كتّاب لم يرَهم النموذج): تطابق تام={acc:.3f} | حسب الطول={by_len}')
if acc >= best:
    export_onnx()
ok = -1
try:
    import onnxruntime as ort
    model.eval().cpu()            # فحص التكافؤ على CPU (التصدير الدوري أعاده لـGPU)
    sess = ort.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
    ok = 0
    with torch.no_grad():
        for a, _, txt in val_set[:32]:
            x = np.zeros((1, 1, STRIP_H, a.shape[1]), np.float32); x[0, 0] = a
            t_out = greedy_decode(model(torch.from_numpy(x)))[0]
            o_out = greedy_decode(torch.from_numpy(sess.run(None, {'image': x})[0]))[0]
            ok += int(t_out == o_out)
    print(f'تكافؤ ONNX/PyTorch: {ok}/32')
except Exception as exc:
    print(f'تحذير: فحص التكافؤ تعذّر ({type(exc).__name__}) — النموذج والمقاييس محفوظة')

with open(f'{OUT}/metrics.json', 'w', encoding='utf-8') as f:
    json.dump({'exact_match': acc, 'by_length': by_len, 'onnx_parity': f'{ok}/32',
               'val_writers': 'MADBase test split (unseen writers)'}, f, indent=1)
print('اكتمل — نزّل: handwritten_digits_crnn.onnx + charset.json + metrics.json + sanity_samples.png')
