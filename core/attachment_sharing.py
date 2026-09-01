# -*- coding: utf-8 -*-
"""
مشاركة المرفقات مع الجهات الخارجية — Attachment Sharing
=======================================================

عند إرسال كتاب بالبريد إلى جهة، نُرفِق ملفاته بالرسالة. لكن خوادم البريد ترفض
الرسائل الكبيرة (Gmail: ~25MB **بعد** ترميز base64 الذي يضخّم الحجم ~37%)، فلا
يمكن إرفاق كل شيء دائماً.

الحلّ: ميزانية إرفاق صارمة. ما يدخل تحتها يُرفَق فعلاً؛ وما يتجاوزها يُستبدَل
بـ**رابط تحميل موقّع محدود المدة** يفتحه المستلم دون تسجيل دخول.

قواعد الأمان لهذا الرابط:
* موقّع تشفيرياً بمفتاح المشروع (``SECRET_KEY``) — لا يمكن تخمينه أو تزويره.
* ينتهي تلقائياً (افتراضياً 7 أيام) — لا وصول دائم.
* يفتح **مرفقاً واحداً بعينه** — لا يعطي أي وصول لبقيّة النظام.
* المرفق المحذوف (soft-delete) لا يُخدَم حتى لو كان الرابط صالحاً.

مَن يملك الرابط يفتح الملف — وهذه هي طبيعة الغرض (إيصال مستند إلى جهة خارجية
لا حساب لها). لذا لا يُصدَر رابط إلا بفعلٍ صريح من موظّف.
"""

import logging
import mimetypes
import os

from django.core import signing

logger = logging.getLogger(__name__)

# ── الميزانية ────────────────────────────────────────────────────────────────
#: حدّ Gmail ~25MB يُقاس على الرسالة **بعد** base64 (تضخيم ≈ 4/3 + ترويسات).
#: فنُبقي البايتات الخام تحت 18MB كي تبقى الرسالة المُرمَّزة تحت الحد بأمان.
MAX_EMAIL_ATTACH_BYTES = 18 * 1024 * 1024

#: صلاحية رابط التحميل الموقّع.
SHARE_LINK_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 أيام

_SIGNING_SALT = 'core.attachment_sharing.v1'


# ── الرابط الموقّع ───────────────────────────────────────────────────────────
def make_share_token(attachment_id: int) -> str:
    """يُصدر رمزاً موقّعاً يفتح هذا المرفق وحده."""
    return signing.dumps({'aid': int(attachment_id)}, salt=_SIGNING_SALT)


def read_share_token(token: str, max_age: int = SHARE_LINK_MAX_AGE_SECONDS):
    """يفكّ الرمز ويعيد ``attachment_id``، أو ``None`` إن كان مزوّراً أو منتهياً."""
    try:
        data = signing.loads(token, salt=_SIGNING_SALT, max_age=max_age)
    except signing.SignatureExpired:
        logger.info("attachment share: رمز منتهي الصلاحية")
        return None
    except signing.BadSignature:
        logger.warning("attachment share: رمز غير صالح أو مزوّر")
        return None
    aid = data.get('aid')
    return int(aid) if aid is not None else None


def build_share_url(request, attachment) -> str:
    """رابط تحميل مطلق (يصلح للوضع داخل بريد) لهذا المرفق."""
    from django.urls import reverse
    path = reverse('attachment_share', args=[make_share_token(attachment.pk)])
    return request.build_absolute_uri(path)


# ── تجميع المرفقات ضمن الميزانية ─────────────────────────────────────────────
def _guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def email_filename(book, attachment, index: int, total: int) -> str:
    """اسم الملف كما تراه الجهة المستلِمة.

    لا نُرسل اسم التخزين الداخلي (``20260003_scan_JZM9Kks.pdf``): فيه لاحقة
    عشوائية يضيفها Django لفضّ تعارض الأسماء، ولا يليق بمستند رسمي. والاسم
    الأصلي غير محفوظ في النموذج أصلاً — فنولّد اسماً رسمياً من رقم الكتاب،
    وهو أوضح للمستلِم من أي اسم عشوائي.
    """
    ext = os.path.splitext(attachment.filename)[1] or '.pdf'
    base = (book.our_number or 'document').replace('/', '-').replace('\\', '-').strip()
    return f"{base}{ext}" if total <= 1 else f"{base}_{index}{ext}"


def plan_book_attachments(book, max_bytes: int = MAX_EMAIL_ATTACH_BYTES):
    """يخطّط ما سيُرفَق فعلاً وما سيُحال إلى رابط — **بلا قراءة بايتات**.

    تفصل المعاينة عن الإرسال: الواجهة تعرض الخطة (أسماء وأحجام) قبل أن يضغط
    المستخدم «أرسل»، ولا يصحّ أن نقرأ عشرات الميغابايتات لمجرّد العرض.

    يُرفَق الأصغر أولاً كي يدخل أكبر عدد ممكن تحت الميزانية. لا اقتطاع صامت:
    كل ملف يقع في ``attach`` أو ``link`` أو ``failed``.

    Returns:
        dict: {'attach': [item...], 'link': [item...], 'failed': [{'name','error'}],
               'attach_bytes': int, 'total_bytes': int}
        حيث item = {'attachment', 'name', 'size'}
    """
    plan = {'attach': [], 'link': [], 'failed': [], 'attach_bytes': 0, 'total_bytes': 0}

    sized = []
    for att in book.attachments.filter(is_deleted=False).order_by('uploaded_at'):
        try:
            sized.append((att.file.size, att))
        except Exception as e:  # الملف مفقود على القرص
            logger.warning("plan_book_attachments: تعذّر قياس %s — %s", att.pk, e)
            plan['failed'].append({'name': att.filename, 'error': 'الملف غير موجود على القرص'})

    # الترقيم الرسمي يتبع ترتيب الرفع (لا ترتيب الحجم) كي يطابق ما يراه المستخدم.
    total = len(sized)
    names = {att.pk: email_filename(book, att, i, total) for i, (_s, att) in enumerate(sized, start=1)}

    sized.sort(key=lambda pair: pair[0])  # الأصغر أولاً — يزيد ما يدخل تحت الميزانية

    budget = max_bytes
    for size, att in sized:
        item = {'attachment': att, 'name': names[att.pk], 'size': size}
        plan['total_bytes'] += size
        if size <= budget:
            plan['attach'].append(item)
            plan['attach_bytes'] += size
            budget -= size
        else:
            plan['link'].append(item)

    return plan


def collect_book_attachments(book, request, max_bytes: int = MAX_EMAIL_ATTACH_BYTES):
    """ينفّذ الخطة: يقرأ بايتات ما يُرفَق، ويُصدر روابط موقّعة لما يتجاوز الميزانية.

    Returns:
        dict: {
          'attachments': [(filename, bytes, mime), ...],   # تُمرَّر لمحرّك SMTP
          'linked':      [{'name', 'size', 'url'}, ...],   # تجاوزت الميزانية
          'failed':      [{'name', 'error'}, ...],
          'attached_bytes': int,
        }
    """
    plan = plan_book_attachments(book, max_bytes=max_bytes)
    result = {
        'attachments': [],
        'linked': [],
        'failed': list(plan['failed']),
        'attached_bytes': 0,
    }

    for item in plan['attach']:
        att, name = item['attachment'], item['name']
        try:
            att.file.open('rb')
            content = att.file.read()
        except Exception as e:
            logger.warning("collect_book_attachments: تعذّرت قراءة %s — %s", att.pk, e)
            result['failed'].append({'name': name, 'error': 'تعذّرت قراءة الملف'})
            continue
        finally:
            try:
                att.file.close()
            except Exception:
                pass

        result['attachments'].append((name, content, _guess_mime(name)))
        result['attached_bytes'] += item['size']

    for item in plan['link']:
        result['linked'].append({
            'name': item['name'],
            'size': item['size'],
            'url': build_share_url(request, item['attachment']),
        })

    return result


def human_size(num_bytes: int) -> str:
    """حجم مقروء بالعربية — يُستخدم في نصّ الرسالة وفي الواجهة."""
    if num_bytes < 1024:
        return f"{num_bytes} بايت"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} ك.ب"
    return f"{num_bytes / (1024 * 1024):.1f} م.ب"
