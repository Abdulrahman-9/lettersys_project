#!/usr/bin/env python
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
django.setup()

from core.models import Entity

# جلب جميع الجهات النشطة
entities = list(Entity.objects.filter(is_active=True).order_by('name').values('id', 'name', 'code', 'etype'))

print("=" * 80)
print("📋 قائمة الجهات المسجلة والمرمزة")
print("=" * 80)
print(json.dumps(entities, ensure_ascii=False, indent=2))
print("=" * 80)
print(f"\nإجمالي الجهات النشطة: {len(entities)}")

# إحصائيات
with_codes = [e for e in entities if e['code']]
without_codes = [e for e in entities if not e['code']]

print(f"جهات مرمزة: {len(with_codes)}")
print(f"جهات بدون رموز: {len(without_codes)}")

if with_codes:
    print("\n✅ الجهات المرمزة:")
    for e in with_codes:
        print(f"  • {e['name']:30} (الرمز: {e['code']:10} - النوع: {e['etype']})")

if without_codes:
    print("\n⚠️  جهات بدون رموز:")
    for e in without_codes:
        print(f"  • {e['name']:30} (النوع: {e['etype']})")
