# وكيل المسح المحلي — LetterSys Scan Agent

خدمة محلية صغيرة تجسر بين المتصفح والماسح الضوئي (TWAIN/WIA/ADF) عبر **NAPS2**،
وتُعيد PDF متعدد الصفحات. تستمع على `127.0.0.1:17865` فقط (لا وصول من الشبكة).

## المتطلبات
1. **NAPS2** (مجاني): ثبّته من <https://www.naps2.com/> — أو ضع نسخة محمولة في
   `scan_agent/naps2_portable/NAPS2.Console.exe`. (يمكن تحديد مسار مخصّص عبر متغيّر
   البيئة `NAPS2_CONSOLE`.)
2. Python (يُفضّل venv المشروع — يوفّر PyMuPDF لعدّ الصفحات، وهو اختياري).

## التشغيل
```bat
REM يدوياً (مع نافذة لرؤية السجل أثناء التطوير):
python -m scan_agent

REM صامتاً (بلا نافذة) — أو ضع اختصار run_agent.bat في مجلد بدء التشغيل (shell:startup):
scan_agent\run_agent.bat
```

## التحقّق السريع (بلا ماسح)
```bash
curl http://127.0.0.1:17865/agent/health
# {"ok": true, "naps2_available": true/false, ...}
```

## الاختبار الكامل (بماسح فعلي)
1. شغّل الخادم: `python manage.py runserver 127.0.0.1:8000`
2. شغّل الوكيل: `python -m scan_agent`
3. افتح «الإدخال الذكي» — يظهر مؤشّر «جاهز: <اسم الماسح>».
4. ضع الورق في الـADF واضغط «مسح من السكانر» → يُمسح → يُرفع → تظهر المعاينة وتُملأ الحقول.

## النقاط (Agent API)
| النقطة | الوصف |
|--------|-------|
| `GET /agent/health` | حياة الوكيل + توفّر NAPS2 (بلا token) |
| `GET /agent/devices?driver=twain` | سرد الماسحات (يتطلّب `X-LetterSys-Token`) |
| `POST /agent/scan` | مسح → PDF ثنائي (نجاح) أو JSON خطأ. يتطلّب token |

## الأمن
- ربط `127.0.0.1` فقط · فحص رأس `Origin` (يُقبل أصل التطبيق فقط) · `token` مشترك في
  `%LOCALAPPDATA%\LetterSys\agent_token.txt` (يقرأه Django ويمرّره للصفحة) · قوائم بيضاء
  لكل معاملات NAPS2 (لا حقن أوامر — تمرير كوسائط منفصلة بلا shell).

## استكشاف الأخطاء
- المؤشّر «NAPS2 غير مثبّت» → ثبّت NAPS2 أو اضبط `NAPS2_CONSOLE`.
- «لا يوجد ماسح متصل» → تأكّد أن الماسح مشغّل ومتصل، وجرّب `NAPS2.Console.exe --listdevices --driver twain` يدوياً.
- «وكيل المسح غير مشغّل» → شغّل `run_agent.bat`.
