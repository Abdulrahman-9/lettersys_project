# -*- coding: utf-8 -*-
"""حسابُ متغيّرَي e2e-E من تشغيلةٍ واحدة — البوّابةُ مسجَّلةٌ سلفاً في السجلّ.

المتغيّر ١ «الصارمُ وحدَه»: يُصدر النصّيَّ ويتخطّى البصريَّ (المكسب 94×).
المتغيّر ٢ «التصادق»: يُشغّل البصريَّ أيضاً — تطابقٌ ⟵ إصدار · خلافٌ ⟵ صمتٌ
مؤشَّر · صمتُ البصريّ ⟵ إصدارُ النصّيّ مؤشَّراً.

والقياسُ على **حقيقة المطبوع المحكَّمة بالعين**، لا على وسم القاعدة — الوسمُ
ملوَّثٌ بنيويّاً (الكاتبُ الذي لا يقرأ الإنكليزيّة ينسخ رقمَ ختمِنا).
"""
import json
import sys

RES = r'D:\migration\lettersys_models\e2e_E_results.json'
rows = json.load(open(RES, encoding='utf-8'))
scored = [r for r in rows if r.get('truth')]      # ما له مرجعٌ مطبوعٌ محكَّم


def tally(pred_of, title):
    fire = hit = wrong = 0
    bad = []
    for r in scored:
        p = pred_of(r)
        if not p:
            continue
        fire += 1
        if p == r['truth']:
            hit += 1
        else:
            wrong += 1
            bad.append((r['book'], p, r['truth']))
    prec = (100.0 * hit / fire) if fire else 0.0
    print('\n— %s —' % title)
    print('  أطلق %d · إصابة %d · خاطئ %d · دقّةُ المُطلَق %.0f%% · صمت %d'
          % (fire, hit, wrong, prec, len(scored) - fire))
    if bad:
        print('  الخاطئ:', bad)
    return {'fire': fire, 'hit': hit, 'wrong': wrong, 'prec': prec}


def concord(r):
    s, v = r.get('strict') or '', r.get('visual') or ''
    if s and v:
        return s if s == v else ''          # خلافٌ ⟵ صمتٌ مؤشَّر
    if s and not v:
        return s                            # صمتُ البصريّ ⟵ النصّيّ مؤشَّراً
    return v                                # لا نصّيَّ ⟵ البصريُّ كما اليوم


print('المجموع %d · ذواتُ مرجعٍ مطبوعٍ محكَّم %d (البقيّةُ بلا مرجعٍ فلا تُحاسَب)'
      % (len(rows), len(scored)))
by_src = {}
for r in scored:
    by_src[r.get('truth_src', '')] = by_src.get(r.get('truth_src', ''), 0) + 1
print('مصدرُ الحقيقة:', by_src)

v_only = tally(lambda r: r.get('visual') or '', 'البصريُّ وحدَه (خطُّ الأساس اليوم)')
s_only = tally(lambda r: r.get('strict') or '', 'المتغيّر ١ — الصارمُ وحدَه')
both = tally(concord, 'المتغيّر ٢ — التصادق')

tt = sum(r.get('t_text', 0) for r in rows)
tv = sum(r.get('t_visual', 0) for r in rows)
n = max(len(rows), 1)
print('\nالزمن: نصّيّ %.3f ث/مستند · بصريّ %.2f ث/مستند (أسرع %.0f×)'
      % (tt / n, tv / n, (tv / tt) if tt else 0))

# تفكيكٌ تشخيصيّ (البوّابةُ على المجمّع)
ents = {}
for r in scored:
    e = (r.get('entity') or '—')[:20]
    d = ents.setdefault(e, [0, 0, 0])
    d[0] += 1
    d[1] += 1 if (r.get('strict') and r['strict'] == r['truth']) else 0
    d[2] += 1 if (r.get('strict') and r['strict'] != r['truth']) else 0
print('\nتفكيكٌ جهويٌّ (تشخيصٌ لا بوّابة): ')
for e, d in sorted(ents.items(), key=lambda x: -x[1][0]):
    print('  %-22s ن=%-3d إصابة %-3d خاطئ %d' % (e, d[0], d[1], d[2]))

G = {'hit_min': 21, 'wrong_strict_max': 3, 'wrong_concord_max': 1, 'prec_min': 90.0}
print('\n════ الحكم على البوّابة المسجَّلة ════')
print('  إصابة (الصارم) %d ≥ %d %s' % (s_only['hit'], G['hit_min'],
                                       '✅' if s_only['hit'] >= G['hit_min'] else '❌'))
print('  إصابة (التصادق) %d ≥ %d %s' % (both['hit'], G['hit_min'],
                                        '✅' if both['hit'] >= G['hit_min'] else '❌'))
print('  خاطئ الصارم %d ≤ %d %s' % (s_only['wrong'], G['wrong_strict_max'],
                                    '✅' if s_only['wrong'] <= G['wrong_strict_max'] else '❌'))
print('  خاطئ التصادق %d ≤ %d %s' % (both['wrong'], G['wrong_concord_max'],
                                     '✅' if both['wrong'] <= G['wrong_concord_max'] else '❌'))
for nm, d in (('الصارم', s_only), ('التصادق', both)):
    print('  دقّةُ المُطلَق %s %.0f%% ≥ 90%% %s' % (nm, d['prec'],
                                                  '✅' if d['prec'] >= G['prec_min'] else '❌'))
shared = [(r['book'], r['strict']) for r in scored
          if r.get('strict') and r.get('visual') and r['strict'] == r['visual']
          and r['strict'] != r['truth']]
print('  المُبطِل (خطأٌ اتّفق عليه المساران): %d %s'
      % (len(shared), shared if shared else '✅'))
