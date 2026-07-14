# -*- coding: utf-8 -*-
# الترقيم الدائم: (1) تجريد بادئة «قديم-» من legacy_number،
# (2) ترحيل كتب 2026 (9-خانة نظيفة) إلى الصيغة الدائمة {R}{NNNN} بإسقاط السنة،
# (3) إعادة بذر عدّادات BookSequence على أكبر تسلسل دائم لكل سجل + 1.
# ملاحظة: بلا طباعة عربية (تكسر cp1256 على ويندوز — راجع CLAUDE.md).
from django.db import migrations
from django.db.models.functions import Substr

# خريطة رمز السجل (مكرّرة هنا لأن apps.get_model لا يحمل خصائص الصنف)
REGISTER_CODES = {
    'incoming_internal': '1',
    'incoming_external': '2',
    'outgoing_internal': '3',
    'outgoing_external': '4',
}
_LEGACY_PREFIX = 'قديم-'  # 5 أحرف


def _is_historical(onum):
    """رقم تاريخي بصيغة السنة (YYYY... بطول ≥ 8)."""
    return len(onum) >= 8 and onum[:4].isdigit() and 2020 <= int(onum[:4]) <= 2099


def forward(apps, schema_editor):
    Book = apps.get_model('core', 'Book')
    BookSequence = apps.get_model('core', 'BookSequence')

    # (1) تجريد «قديم-» من legacy_number (استعلام واحد فعّال)
    Book.objects.filter(legacy_number__startswith=_LEGACY_PREFIX).update(
        legacy_number=Substr('legacy_number', len(_LEGACY_PREFIX) + 1)
    )

    # (2) ترحيل كتب 2026 النظيفة (9-خانة، غير مركّبة) إلى الدائم {R}{NNNN}
    qs = Book.objects.filter(our_number__startswith='2026', series_no__isnull=True)
    for book in qs.iterator(chunk_size=2000):
        o = book.our_number or ''
        if len(o) == 9 and o[:4] == '2026' and o[4] in '1234' and o[5:].isdigit():
            new = o[4:]  # إسقاط '2026' → {R}{NNNN}
            # حارس تفرّد دفاعي: لا نكتب فوق رقم دائم موجود لنفس النوع
            if not Book.objects.filter(our_number=new, kind=book.kind).exclude(pk=book.pk).exists():
                book.our_number = new
                book.save(update_fields=['our_number'])

    # (3) إعادة بذر العدّادات على أكبر تسلسل دائم لكل سجل + 1.
    #     مهم: لا نُنزل العدّاد أبداً هنا (max مع القيمة الحالية) — قد يوجد حجز نشط
    #     لرقم أعلى. التنزيل المتعمّد لاستعادة الأرقام يكون في purge_dev_seed_books
    #     عند الاعتماد (بعد حذف الكتب التجريبية وحجوزاتها).
    for kind, reg in REGISTER_CODES.items():
        max_seq = 0
        for onum in Book.objects.filter(
            kind=kind, our_number__startswith=reg
        ).values_list('our_number', flat=True):
            if not onum or not onum.isdigit() or _is_historical(onum):
                continue
            seq_part = onum[len(reg):]
            if seq_part.isdigit():
                max_seq = max(max_seq, int(seq_part))
        computed = max_seq + 1 if max_seq else 1
        obj, created = BookSequence.objects.get_or_create(
            kind=kind, defaults={'next_number': computed, 'year': 2026}
        )
        if not created:
            new_next = max(obj.next_number, computed)  # لا ننزل تحت الحالي
            if obj.next_number != new_next:
                obj.next_number = new_next
                obj.save(update_fields=['next_number'])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0051_backupsettings_securitysettings'),
    ]
    operations = [
        # تحويل بيانات أحادي الاتجاه (إسقاط السنة لا يمكن استرجاعه بأمان).
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
