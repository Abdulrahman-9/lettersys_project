# -*- coding: utf-8 -*-
"""استطلاعُ S‑0 — يحسم «أحُمِّلت بياناتُ 2026-09-08 على الإنتاج أم لا؟»

**قراءةٌ فقط.** لا `UPDATE` ولا `INSERT` ولا `migrate` — يُقرأ ويُلصق مخرَجُه في
`Merge9.md` (§8 وسجلّ التنفيذ). يُشغَّل على الخادم:

    cd /var/www/lettersys && .venv/bin/python manage.py shell -c "exec(open('scripts/probe_s0.py').read())"

**على ويندوز** أضف الترميزَ صراحةً وإلّا خرج النصُّ العربيُّ مشوَّهاً (``open``
يأخذ ترميزَ المحلّيّة لا UTF-8)::

    python manage.py shell -c "exec(open('scripts/probe_s0.py', encoding='utf-8').read())"

ولا يحتاج ``psql`` في المسار — وهو سببُ وجوده: صيغةُ ``dbshell -- -Atc`` تعتمد على
عميل psql، وغيابُه عن المسار يوقف الاستطلاع عند أوّل خطوة.

**لماذا هذه الأعمدةُ بعينها:** ``loaddata`` **ذرّيّ** (يلفّ الملفَّ في معاملةٍ واحدة)،
فلا وجودَ لتحميلٍ جزئيّ من ملفٍّ واحد: إمّا الكلُّ أو صفر. لكنّ المحاولةَ الفاشلة
تترك بصمةً لا تُمحى: ``n_tup_ins`` يعدّ الصفوفَ المُدخَلة **حتّى في المعاملات
المُلغاة** (تصير صفوفاً ميّتة) و``xact_rollback`` يزيد. فـ«صفرُ كتبٍ مع
``ins≈13,194``» يعني «حُوِّل وانقطع» لا «لم يُحاوَل».

و``ids>13386`` هو عدّادُ العمل الحقيقيّ فوق المُحمَّل: ``loaddata`` يضبط تسلسلَ
المفاتيح عند 13386، فكلُّ معرِّفٍ أعلى منه كتابٌ أدخله موظّفٌ **بعد** التحميل.
"""

from django.db import connection

#: خطُّ الأساس المحلّيّ (قِيس 2026-09-10 على القاعدة المُجمَّدة) — للمقارنة لا للحكم.
#:
#: ⚠️ **العدّاداتُ تحرّكت عن مرجع §10.2** (`2433/358/455`، وهو مقيسُ 2026-08-17):
#: القياسُ اليومَ `incoming_internal=3917 · outgoing_internal=715 ·
#: incoming_external=605` **وصفٌّ رابعٌ `outgoing_external=1`** لم يكن،
#: و`updated_at` عليها 08-24 و08-30 — أي عملٌ حقيقيٌّ بعد إعادة البناء.
#: كلُّ ما عداها يطابق §10.2 حرفيّاً. لا تُعدَّل بوّابةٌ بعد النظر — يُسجَّل الفارق.
LOCAL = {
    'books': 13239, 'training': 131, 'deleted': 45,
    'entities': 674, 'merged_into': 256, 'active_entities': 353,
    'history': 22313, 'attachments': 13187, 'sessions': 282,
    'letterhead_memory': 5395, 'bookemaillog': 'sent=1',
    'sequences': ('incoming_external=605 incoming_internal=3917 '
                  'outgoing_external=1 outgoing_internal=715'),
    'active_users': 12, 'mail': 'enc=True len=125 imap=True active=True',
    'migration': '0077_archive_events_and_history',
}

PROBES = (
    ('books  الكتب/الجديد/التدريب/آخر إنشاء',
     "select count(*), count(*) filter (where id>13386), "
     "count(*) filter (where is_training), coalesce(max(created_at)::text,'-') "
     "from core_book"),
    ('entities  الجهات', "select count(*), coalesce(max(id),0) from core_entity"),
    # ── البصماتُ (N4، تعارضُ C13): بوّابتا 10.j/10.k تصيران نسخاً ولصقاً ──────
    # الأعدادُ ليست بصمة (§10.1): نسخةُ 09-08 أعدادُها تطابق الحيّةَ حرفيّاً
    # ومحتواها أقدم — `merged_into` 198 مقابل 256. وهذه الأسطرُ هي نفسُها التي
    # يطبعها `verify_backup`، فيُقارَن الطرفان بلا اجتهاد.
    ('entity_fp  مدموجة/نشطة',
     "select count(*) filter (where merged_into_id is not null), "
     "count(*) filter (where is_active) from core_entity"),
    ('book_fp  محذوفٌ ناعماً',
     "select count(*) filter (where is_deleted) from core_book"),
    ('sequences  عدّاداتُ السجلّات',
     "select coalesce(string_agg(kind || '=' || next_number::text, ' ' "
     "order by kind),'-') from core_booksequence"),
    ('letterhead_memory  ذاكرةُ الترويسة',
     "select count(*) from core_letterheadmemory"),
    ('bookemaillog  لكلّ حالة',
     "select coalesce(string_agg(status || '=' || n::text, ' ' order by status),"
     "'(لا صفوف)') from (select status, count(*) n from core_bookemaillog "
     "group by status) s"),
    ('active_users  المستخدمون النشطون',
     "select count(*), coalesce(string_agg(username,' ' order by username),'-') "
     "from auth_user where is_active"),
    ('history/attach/sessions',
     "select (select count(*) from core_bookhistory),"
     "(select count(*) from core_attachment),(select count(*) from django_session)"),
    ('users  المستخدمون',
     "select count(*), coalesce(string_agg(username,' ' order by username),'-') from auth_user"),
    ('mail  مشفَّر/الطول/IMAP/نشط',
     "select smtp_password like 'enc::%%', length(smtp_password), "
     "imap_sync_enabled, is_active from core_emailsettings"),
    ('incoming_emails  بريدٌ مسحوب', "select count(*) from core_incomingemail"),
    ('pgstat_book  ins/dead/live',
     "select n_tup_ins, n_dead_tup, n_live_tup from pg_stat_user_tables "
     "where relname='core_book'"),
    ('pgstat_db  rollback/الحجم',
     "select xact_rollback, pg_size_pretty(pg_database_size(current_database())) "
     "from pg_stat_database where datname=current_database()"),
    ('active_backends  جلساتٌ تعمل الآن',
     "select count(*) from pg_stat_activity where datname=current_database() "
     "and state<>'idle' and pid<>pg_backend_pid()"),
    ('migration_head  آخرُ هجرة',
     "select name from django_migrations where app='core' order by id desc limit 1"),
)


def _run():
    print('── استطلاعُ S‑0 (قراءةٌ فقط) ' + '─' * 34)
    with connection.cursor() as cur:
        for label, sql in PROBES:
            try:
                cur.execute(sql)
                row = cur.fetchone()
                value = ' | '.join('-' if v is None else str(v) for v in row) if row else '(لا صفّ)'
            except Exception as exc:                      # noqa: BLE001 — استطلاعٌ لا أثر
                # الجدولُ الغائبُ خبرٌ بذاته (مخطّطٌ أقدم) — يُعرض ولا يوقف البقيّة.
                value = 'ERROR %s: %s' % (type(exc).__name__, str(exc).strip()[:70])
            print('%-40s %s' % (label, value))
    print('─' * 62)
    print('الأساسُ المحلّيّ للمقارنة:', LOCAL)
    print('الحكمُ في Merge9.md §8.3 — والمخرَجُ يُلصق في سجلّ التنفيذ.')


_run()
