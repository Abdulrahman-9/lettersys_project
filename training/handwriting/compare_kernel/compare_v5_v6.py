# v5 vs v6 end-to-end on HELD-OUT books (reuses the finetune val split + arch).
# Answers: does v6's wide+tight recipe beat v5 on WIDE crops (the deployment case)?
import os, glob, csv, hashlib, zipfile
import numpy as np
from PIL import Image
import torch, torch.nn as nn

CHARSET, BLANK, NUM_CLASSES, STRIP_H, MAX_W = '0123456789', 0, 11, 64, 512
DEVICE = 'cpu'
print('device', DEVICE, flush=True)

def _find(p):
    h = sorted(glob.glob(p, recursive=True))
    if not h: raise FileNotFoundError(p)
    return h[0]

zp = glob.glob('/kaggle/input/**/strips.zip', recursive=True)
REAL_DIR = '/kaggle/working/strips'
if zp:
    zipfile.ZipFile(zp[0]).extractall(REAL_DIR)
else:
    REAL_DIR = os.path.dirname(_find('/kaggle/input/**/*.png'))

rows = [r for r in csv.DictReader(open(_find('/kaggle/input/**/labels_clean.csv'), encoding='utf-8'))
        if os.path.exists(os.path.join(REAL_DIR, r['file']))]

def _is_val(r):
    return int(hashlib.md5(r['book_id'].encode()).hexdigest(), 16) % 100 < 15 and r['tier'] in ('A', 'B')

# FAIR: only real held-out books (non-empty book_id); v6 held these out.
VAL = [r for r in rows if r['book_id'] and _is_val(r)]
print('rows', len(rows), '| held-out val', len(VAL), flush=True)

def real_to_internal(img):
    w, h = img.size
    nw = max(32, min(MAX_W, int(w * STRIP_H / max(1, h))))
    return Image.fromarray(255 - np.asarray(img.resize((nw, STRIP_H), Image.BILINEAR), dtype=np.uint8))

def _norm(s):
    a = np.asarray(s, dtype=np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)

class CRNN(nn.Module):
    def __init__(self):
        super().__init__()
        def blk(ci, co, pool):
            return nn.Sequential(nn.Conv2d(ci, co, 3, padding=1), nn.BatchNorm2d(co),
                                 nn.ReLU(inplace=True), nn.MaxPool2d(pool))
        self.cnn = nn.Sequential(blk(1, 32, 2), blk(32, 64, 2), blk(64, 128, (2, 1)), blk(128, 128, (2, 1)))
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

def load_model(wp):
    m = CRNN(); m.load_state_dict(torch.load(wp, map_location='cpu')); return m.to(DEVICE).eval()

def greedy(logits):
    out = []
    for seq in logits.argmax(-1).cpu().numpy():
        prev, ch = BLANK, []
        for k in seq:
            if k != BLANK and k != prev: ch.append(CHARSET[k - 1])
            prev = k
        out.append(''.join(ch))
    return out

VP = [(_norm(real_to_internal(Image.open(os.path.join(REAL_DIR, r['file'])).convert('L'))), r) for r in VAL]

def evalm(m):
    res = {}
    for i in range(0, len(VP), 64):
        b = VP[i:i + 64]; W = max(x[0].shape[1] for x in b)
        imgs = np.zeros((len(b), 1, STRIP_H, W), np.float32)
        for j, (a, _) in enumerate(b): imgs[j, 0, :, :a.shape[1]] = a
        with torch.no_grad(): preds = greedy(m(torch.from_numpy(imgs).to(DEVICE)))
        for (a, r), p in zip(b, preds): res[r['file']] = p
    return res

v5w = _find('/kaggle/input/**/crnn_weights.pt')
v6w = _find('/kaggle/input/**/crnn_weights_v5.pt')
print('v5w', v5w, '\nv6w', v6w, flush=True)
r5, r6 = evalm(load_model(v5w)), evalm(load_model(v6w))

def score(res, sub):
    return sum(res[r['file']] == r['label'] for r in sub), len(sub)

wide = [r for r in VAL if r['file'].startswith('w_')]
tight = [r for r in VAL if not r['file'].startswith('w_')]
print('\n===== v5 vs v6 on HELD-OUT books =====', flush=True)
for name, sub in [('ALL', VAL), ('WIDE (w_)', wide), ('TIGHT', tight)]:
    if not sub: continue
    o5, n = score(r5, sub); o6, _ = score(r6, sub)
    print(f'  {name:12} n={n:4}  v5={100*o5//n:3}%  v6={100*o6//n:3}%  (v6-v5={100*o6//n - 100*o5//n:+d})', flush=True)
print('DONE', flush=True)
