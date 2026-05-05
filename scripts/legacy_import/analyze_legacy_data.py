"""
analyze_legacy_data.py
======================
يحلل بيانات النظام القديم المصدّرة من SQL Server
ويبني تقرير كامل + خريطة التحويل إلى نماذج LetterSys

الاستخدام:
    python analyze_legacy_data.py --schema export/schema.txt \
                                  --counts export/row_counts.txt \
                                  --sample export/sample_data.json
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import Counter, defaultdict


# ── خريطة التخمين الذكي للحقول ──────────────────────────────────
# يحاول تخمين المطابقة بناءً على اسم العمود
FIELD_HINTS = {
    # أرقام الكتب
    r'(letter|book|doc|كتاب|مستند)[_\s]?(no|num|number|رقم)': 'Book.our_number',
    r'(sender|from|من)[_\s]?(no|num|number|رقم)':              'Book.sender_number',
    r'(serial|تسلسل|seq)':                                       'Book.our_number',

    # العناوين
    r'(subject|title|موضوع|عنوان)':                             'Book.title',

    # التواريخ
    r'(letter|book|doc)[_\s]?date|تاريخ[_\s]?الكتاب':          'Book.date',
    r'(sender|from)[_\s]?date|تاريخ[_\s]?الجهة':               'Book.sender_date',
    r'(due|followup|متابعة)[_\s]?date':                         'Book.due_date',

    # الاتجاه / النوع
    r'(direction|type|kind|نوع|اتجاه)':                         'Book.kind',
    r'(incoming|وارد)':                                          'Book.kind → incoming_*',
    r'(outgoing|صادر)':                                          'Book.kind → outgoing_*',
    r'(internal|داخلي)':                                         'Book.kind → *_internal',
    r'(external|خارجي)':                                         'Book.kind → *_external',

    # الجهات
    r'(from|sender|issuer|مرسل|مصدر|من)[_\s]?(entity|org|dept|جهة|قسم|دائرة)': 'Entity (issuing)',
    r'(to|receiver|recipient|مستلم|إلى)[_\s]?(entity|org|dept|جهة|قسم|دائرة)': 'Entity (receiving)',
    r'(from|sender|مرسل|من)$':                                   'Entity (issuing)',
    r'(to|receiver|مستلم|إلى)$':                                 'Entity (receiving)',

    # الحالة
    r'(status|state|حالة)':                                      'Book.final_status',
    r'(followup|needs_followup|متابعة)':                         'Book.needs_followup',

    # السرية
    r'(secret|confidential|سري|سرية)':                           'Book.secret_level',

    # الملاحظات
    r'(notes|remarks|margin|ملاحظات|هامش)':                     'Book.margin',
}

STATUS_MAP = {
    # قيم محتملة في النظام القديم → قيم النظام الجديد
    'pending':    'pending',
    'قيد المتابعة': 'pending',
    'done':       'done',
    'منجزة':      'done',
    'مكتملة':     'done',
    'completed':  'done',
    'archived':   'archived',
    'مؤرشف':      'archived',
    'hold':       'hold',
    'معلقة':      'hold',
    'موقوف':      'hold',
    '0':          'pending',
    '1':          'done',
    '2':          'archived',
}

KIND_MAP = {
    'incoming':          'incoming_external',
    'outgoing':          'outgoing_external',
    'وارد':              'incoming_external',
    'صادر':              'outgoing_external',
    'وارد داخلي':        'incoming_internal',
    'وارد خارجي':        'incoming_external',
    'صادر داخلي':        'outgoing_internal',
    'صادر خارجي':        'outgoing_external',
    '1':                 'incoming_external',
    '2':                 'outgoing_external',
    '3':                 'incoming_internal',
    '4':                 'outgoing_internal',
}


def guess_field_mapping(column_name: str) -> str:
    """خمّن المطابقة بناءً على اسم العمود."""
    col_lower = column_name.lower()
    for pattern, target in FIELD_HINTS.items():
        if re.search(pattern, col_lower, re.IGNORECASE):
            return target
    return '❓ غير محدد'


def analyze_schema(schema_file: Path) -> dict:
    """تحليل بنية الجداول وبناء خريطة التحويل."""
    tables = defaultdict(list)
    current_table = None

    print("\n" + "="*60)
    print("  تحليل بنية الجداول")
    print("="*60)

    with open(schema_file, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split() if p.strip()]
            if len(parts) >= 2:
                table, col = parts[0], parts[1]
                dtype = parts[2] if len(parts) > 2 else 'unknown'
                tables[table].append({
                    'column': col,
                    'type': dtype,
                    'mapping': guess_field_mapping(col)
                })

    mapping_report = {}
    for table, cols in tables.items():
        print(f"\n📋 الجدول: {table} ({len(cols)} عمود)")
        mapped = [c for c in cols if '❓' not in c['mapping']]
        unmapped = [c for c in cols if '❓' in c['mapping']]
        print(f"   ✅ أعمدة تم تخمين مطابقتها: {len(mapped)}")
        print(f"   ❓ أعمدة تحتاج مراجعة: {len(unmapped)}")
        for c in cols:
            icon = '✅' if '❓' not in c['mapping'] else '❓'
            print(f"   {icon} {c['column']:30s} ({c['type']:15s}) → {c['mapping']}")
        mapping_report[table] = cols

    return mapping_report


def analyze_sample(sample_file: Path) -> dict:
    """تحليل عينة البيانات الفعلية."""
    print("\n" + "="*60)
    print("  تحليل عينة البيانات")
    print("="*60)

    stats = {}
    try:
        with open(sample_file, encoding='utf-8', errors='replace') as f:
            content = f.read()

        # استخراج جمل JSON من ملف الإخراج
        json_blocks = re.findall(r'\[.*?\]', content, re.DOTALL)
        all_records = []
        for block in json_blocks:
            try:
                records = json.loads(block)
                all_records.extend(records)
            except json.JSONDecodeError:
                pass

        if all_records:
            print(f"\n📊 إجمالي السجلات في العينة: {len(all_records)}")
            # تحليل أول سجل
            if all_records:
                sample = all_records[0]
                print(f"   الحقول: {list(sample.keys())}")
    except Exception as e:
        print(f"   تعذر قراءة عينة البيانات: {e}")

    return stats


def analyze_counts(counts_file: Path):
    """طباعة إحصائيات أعداد السجلات."""
    print("\n" + "="*60)
    print("  إحصائيات أعداد السجلات")
    print("="*60)
    total = 0
    try:
        with open(counts_file, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('-') and not line.startswith('('):
                    print(f"   {line}")
                    # استخراج الأرقام
                    nums = re.findall(r'\d+', line)
                    if nums:
                        total += int(nums[-1])
        print(f"\n   📦 إجمالي السجلات الكلي: {total:,}")
    except FileNotFoundError:
        print("   ملف الإحصائيات لم يُنشأ بعد")


def generate_django_import_config(mapping_report: dict, output_file: Path):
    """توليد ملف إعداد الاستيراد لـ Django."""
    config = {
        "version": "1.0",
        "source": "mssql_legacy",
        "target": "lettersys_django",
        "tables": {}
    }

    for table, cols in mapping_report.items():
        mapped_cols = {c['column']: c['mapping'] for c in cols if '❓' not in c['mapping']}
        if mapped_cols:
            config["tables"][table] = {
                "django_model": _guess_model(mapped_cols),
                "field_map": mapped_cols,
                "skip_if_exists": True,
                "number_prefix": "مستورد-"
            }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n✅ ملف إعداد الاستيراد: {output_file}")


def _guess_model(mapped_cols: dict) -> str:
    values = ' '.join(mapped_cols.values())
    if 'Book.' in values:
        return 'core.Book'
    if 'Entity' in values:
        return 'core.Entity'
    return 'unknown'


def main():
    parser = argparse.ArgumentParser(description='تحليل بيانات النظام القديم')
    parser.add_argument('--schema',  type=Path, default=Path('export/schema.txt'))
    parser.add_argument('--counts',  type=Path, default=Path('export/row_counts.txt'))
    parser.add_argument('--sample',  type=Path, default=Path('export/sample_data.json'))
    parser.add_argument('--output',  type=Path, default=Path('export/import_config.json'))
    args = parser.parse_args()

    print("\n🔍 بدء تحليل بيانات النظام القديم...")

    mapping = {}
    if args.schema.exists():
        mapping = analyze_schema(args.schema)
    else:
        print(f"⚠️  ملف البنية غير موجود: {args.schema}")

    if args.counts.exists():
        analyze_counts(args.counts)
    else:
        print(f"⚠️  ملف الإحصائيات غير موجود: {args.counts}")

    if args.sample.exists():
        analyze_sample(args.sample)
    else:
        print(f"⚠️  ملف العينة غير موجود: {args.sample}")

    if mapping:
        generate_django_import_config(mapping, args.output)

    print("\n✅ اكتمل التحليل!\n")


if __name__ == '__main__':
    main()
