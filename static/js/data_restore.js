/* ============================================================
   data_restore.js — معالج صفحة دمج البيانات من النظام القديم.

   المبدأ: كل نداء هنا قراءةٌ رخيصة أو معاينة. الكتابة الوحيدة هي
   «اعتماد الربط» (يكتب حقل مرجع المصدر فقط) و«الدمج» (نموذج POST عادي).
   الرسائل صادقة: صفر نتائج تُعرَض كصفر، لا كنجاح.

   العرض على الهويّة الموحّدة (11-19): أصنافُ css/data_restore.css وحدها — لا ‎.table‎
   (app.css يلصق خليّتها الأخيرة بخلفيّةٍ بيضاء في الداكن)، ولا شاراتُ Bootstrap الصمّاء،
   والأرقامُ معزولةُ الاتّجاه، وعناصرُ متصفّح الملفّات أزرارٌ تُبلَغ بلوحة المفاتيح.
   ============================================================ */
(function () {
  'use strict';

  var URLS = {};

  // ── أدوات ────────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  function csrf() {
    var el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (el) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function num(n) {
    return (n === null || n === undefined) ? '—' : Number(n).toLocaleString('en-US');
  }

  // رقمٌ معزولُ الاتّجاه داخل جملةٍ أو خليّة (عقدُ الهويّة §5)
  function isoNum(n) { return '<bdi dir="ltr">' + num(n) + '</bdi>'; }

  function bytes(b) {
    if (!b) return '—';
    var u = ['بايت', 'ك.ب', 'م.ب', 'ج.ب'], i = 0, v = Number(b);
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return '<bdi dir="ltr">' + v.toFixed(i ? 1 : 0) + '</bdi> ' + u[i];
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var KIND_LABELS = {
    incoming_internal: 'وارد داخلي',
    incoming_external: 'وارد خارجي',
    outgoing_internal: 'صادر داخلي',
    outgoing_external: 'صادر خارجي'
  };

  function busy(btn, on, label) {
    if (!btn) return;
    if (on) {
      btn.dataset.html = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>' + (label || 'جارٍ التنفيذ…');
    } else {
      btn.disabled = false;
      if (btn.dataset.html) btn.innerHTML = btn.dataset.html;
    }
  }

  // أيقونةٌ لكلّ نوع — المعنى لا يُحمل على اللون وحده
  var ALERT_ICON = {
    success: 'bi-check-circle',
    warning: 'bi-exclamation-triangle',
    danger: 'bi-x-octagon',
    info: 'bi-info-circle'
  };

  function alertBox(kind, html) {
    return '<div class="alert alert-' + kind + ' rs-alert"><i class="bi ' + (ALERT_ICON[kind] || ALERT_ICON.info) +
      '" aria-hidden="true"></i><div>' + html + '</div></div>';
  }

  function table(inner) {
    return '<div class="rs-scroll"><table class="rs-table">' + inner + '</table></div>';
  }

  // لوحُ المراحل يعكس حالةَ كلّ خطوة، و«الآن» على أوّل خطوةٍ متاحة (عرضٌ وحده)
  var TRACK_STATE = { done: 'تمّت', active: 'متاحة', blocked: 'لاحقاً' };

  function syncTrack() {
    var current = null;
    for (var n = 1; n <= 4; n++) {
      var step = document.querySelector('.rs-step[data-step="' + n + '"]');
      var item = document.querySelector('.rs-track [data-step="' + n + '"]');
      if (!step || !item) continue;
      var state = step.getAttribute('data-state');
      var link = item.querySelector('a');
      var label = item.querySelector('[data-track-state]');
      item.setAttribute('data-state', state);
      if (link) link.removeAttribute('aria-current');
      if (state === 'active' && current === null) {
        current = n;
        if (link) link.setAttribute('aria-current', 'step');
      }
      if (label) label.textContent = n === current ? 'الآن' : (TRACK_STATE[state] || '');
    }
  }

  function setStep(n, state) {
    var el = document.querySelector('.rs-step[data-step="' + n + '"]');
    if (el) el.setAttribute('data-state', state);
    syncTrack();
  }

  function creds() {
    return {
      server: $('rsServer').value.trim() || 'localhost',
      database: $('rsDatabase').value.trim() || 'ARCHMDOC',
      username: $('rsUser').value.trim() || 'sa',
      password: $('rsPass').value
    };
  }

  function post(url, extra) {
    var c = creds();
    var body = new URLSearchParams();
    body.set('server', c.server);
    body.set('database', c.database);
    body.set('username', c.username);
    body.set('password', c.password);
    Object.keys(extra || {}).forEach(function (k) { body.set(k, extra[k]); });
    return fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: body.toString()
    }).then(function (r) {
      if (!r.ok) throw new Error('استجابة غير متوقّعة من الخادم (' + r.status + ')');
      return r.json();
    });
  }

  function paintState(state) {
    if (!state) return;
    Object.keys(state).forEach(function (k) {
      var el = document.querySelector('#rsState [data-stat="' + k + '"]');
      if (el) el.textContent = num(state[k]);
    });
  }

  function failure(out, err) {
    out.innerHTML = alertBox('danger',
      '<strong>تعذّر التنفيذ.</strong> ' + esc(err) +
      '<div class="rs-note">تحقّق من اسم الخادم وقاعدة البيانات وكلمة السر، ' +
      'ومن أن خدمة SQL Server تعمل.</div>');
  }

  // ── الخطوة ١: فحص الاتصال ────────────────────────────────────────────
  function probe() {
    var btn = $('rsProbeBtn'), out = $('rsProbeOut');
    busy(btn, true, 'جارٍ الفحص…');
    out.innerHTML = '';
    post(URLS.probe).then(function (d) {
      busy(btn, false);
      if (!d.ok) { failure(out, d.error); setStep(1, 'active'); return; }
      paintState(d.state);

      if (!d.tables.length) {
        out.innerHTML = alertBox('warning',
          '<strong>الاتصال نجح، لكن لا توجد جداول مراسلات</strong> بالصيغة المتوقّعة ' +
          '(<code>IIMAIL_YYYY</code> …) في قاعدة «' + esc(creds().database) + '». ' +
          'تأكّد من اسم القاعدة.');
        setStep(1, 'active');
        return;
      }

      var rows = d.tables.map(function (t) {
        return '<tr><td><code>' + esc(t.table) + '</code></td>' +
               '<td>' + esc(KIND_LABELS[t.kind] || t.kind) + '</td>' +
               '<td class="rs-num">' + isoNum(t.rows) + '</td>' +
               '<td class="rs-num">' + isoNum(t.with_file) + '</td></tr>';
      }).join('');

      out.innerHTML =
        alertBox('success', '<strong>الاتصال ناجح.</strong> ' + isoNum(d.tables.length) +
          ' جدولاً، ' + isoNum(d.total_rows) + ' سجلاً، السنوات: ' + esc(d.years.join('، ')) + '.') +
        table('<thead><tr><th scope="col">الجدول</th><th scope="col">النوع</th>' +
          '<th scope="col">الصفوف</th><th scope="col">بمرفق</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>');

      setStep(1, 'done');
      setStep(2, 'active');
      setStep(3, 'active');
    }).catch(function (e) {
      busy(btn, false);
      failure(out, e.message);
    });
  }

  // ── الخطوة ٢: المطابقة ───────────────────────────────────────────────
  // حواريّةُ التطبيق لا نافذةُ المتصفّح الأصليّة (H4) — وعدٌ بنعم/لا
  function ask(opts) {
    return window.confirmDelete ? window.confirmDelete(opts)
                                : Promise.resolve(window.confirm(opts.message));
  }

  function reconcile(apply) {
    if (!apply) { runReconcile(false); return; }
    ask({
      title: 'اعتماد الربط',
      message: 'سيُكتب حقل «مرجع المصدر» فقط على الكتب المُطابَقة.\nلا يتغيّر أي رقم أو عنوان أو مرفق.',
      okText: 'اعتمد الربط',
      danger: false
    }).then(function (ok) { if (ok) runReconcile(true); });
  }

  function runReconcile(apply) {
    var btn = apply ? $('rsReconcileApply') : $('rsReconcilePreview');
    var out = $('rsReconcileOut');
    busy(btn, true, apply ? 'جارٍ الربط…' : 'جارٍ المطابقة…');
    out.innerHTML = '';

    var v = parseInt($('rsVerify').value, 10);
    post(URLS.reconcile, { apply: apply ? '1' : '0', verify_bytes: isNaN(v) ? 40 : v })
      .then(function (d) {
        busy(btn, false);
        if (!d.ok) { failure(out, d.error); return; }
        paintState(d.state);

        if (d.aborted) {
          out.innerHTML = alertBox('danger', '<strong>أُلغي الربط.</strong> ' + esc(d.aborted));
          return;
        }

        var verifyLine = '';
        if (d.verified_bytes) {
          verifyLine = d.verify_mismatches.length
            ? '<div class="rs-note text-danger"><i class="bi bi-x-octagon" aria-hidden="true"></i>تحقّق البصمات: ' +
              isoNum(d.verify_mismatches.length) + ' اختلافاً من ' + isoNum(d.verified_bytes) + ' — لم يُعتمد شيء.</div>'
            : '<div class="rs-note text-success"><i class="bi bi-shield-check" aria-hidden="true"></i>تحقّق البصمات: ' +
              isoNum(d.verified_bytes) + ' مرفقاً من <strong>مطابقات الحجم</strong> قُورنت — تطابق تامّ.</div>';
        }
        var attn = (d.attention || []).length;
        if (attn) {
          verifyLine += '<div class="rs-note text-warning-emphasis">' +
            '<i class="bi bi-eye" aria-hidden="true"></i><strong>' + isoNum(attn) + '</strong> كتاباً رُبط بالعنوان والتاريخ ' +
            'لا بحجم المرفق — الفارق طبيعي إن استبدلتَ المرفق داخل التطبيق، وإلا فراجعها.</div>';
        }

        var body = table('<tbody>' +
          '<tr><th scope="row">صفوف المصدر</th><td class="rs-num"><strong>' + isoNum(d.source_rows) + '</strong></td></tr>' +
          '<tr><th scope="row">كتب بلا ربط قبل التشغيل</th><td class="rs-num">' + isoNum(d.books_without_ref) + '</td></tr>' +
          '<tr><th scope="row">مُطابَقة بمفتاح فريد</th><td class="rs-num text-success"><strong>' + isoNum(d.matched) + '</strong></td></tr>' +
          '<tr class="rs-sub"><th scope="row">منها بحجم المرفق</th><td class="rs-num">' + isoNum(d.matched_by_size) + '</td></tr>' +
          '<tr class="rs-sub"><th scope="row">منها بالعنوان والتاريخ</th><td class="rs-num">' + isoNum(d.matched_by_title) + '</td></tr>' +
          '<tr><th scope="row">ملتبسة (تُركت دون ربط)</th><td class="rs-num">' + isoNum(d.ambiguous) + '</td></tr>' +
          '<tr><th scope="row">كتب بلا مطابقة (كتبك غالباً)</th><td class="rs-num">' + isoNum(d.unmatched_books) + '</td></tr>' +
          '<tr><th scope="row">صفوف مصدر بلا مطالبة</th><td class="rs-num">' + isoNum(d.unclaimed_source_rows) + '</td></tr>' +
          '</tbody>');

        if (d.applied) {
          out.innerHTML = alertBox('success',
            '<strong>تمّ الربط.</strong> خُتم «مرجع المصدر» على ' + isoNum(d.matched) + ' كتاباً.' + verifyLine) + body;
          $('rsReconcileApply').disabled = true;
          setStep(2, 'done');
          setStep(3, 'active');
        } else if (d.matched === 0) {
          out.innerHTML = alertBox('info',
            '<strong>لا جديد ليُربط.</strong> كل ما يمكن ربطه مربوطٌ سلفاً — يمكنك المضيّ للخطوة ٣.' + verifyLine) + body;
          $('rsReconcileApply').disabled = true;
          setStep(2, 'done');
          setStep(3, 'active');
        } else {
          out.innerHTML = alertBox('warning',
            '<strong>معاينة — لم يُكتب شيء.</strong> سيُربط ' + isoNum(d.matched) +
            ' كتاباً عند الاعتماد.' + verifyLine) + body;
          $('rsReconcileApply').disabled = false;
        }
      }).catch(function (e) {
        busy(btn, false);
        failure(out, e.message);
      });
  }

  // ── الخطوة ٣: معاينة الفرق ───────────────────────────────────────────
  function delta() {
    var btn = $('rsDeltaBtn'), out = $('rsDeltaOut');
    busy(btn, true, 'جارٍ المقارنة…');
    out.innerHTML = '';
    post(URLS.delta).then(function (d) {
      busy(btn, false);
      if (!d.ok) { failure(out, d.error); return; }
      paintState(d.state);

      var t = d.totals || {};

      var footnotes = '';
      if (t.app_only) {
        footnotes += '<div class="rs-note">لديك ' + isoNum(t.app_only) +
          ' كتاباً لا وجود له في المصدر — أدخلتَها داخل التطبيق، ولن يمسّها الدمج.</div>';
      }
      if (t.held) {
        footnotes += '<div class="rs-note">' +
          '<i class="bi bi-pause-circle" aria-hidden="true"></i><strong>' + isoNum(t.held) + ' صفّاً موقوفاً:</strong> ' +
          'كان موجوداً في المصدر قبل آخر مزامنة ولم يُستورد — غالباً تعميم مكرّر تُرك عمداً. ' +
          '<strong>لا يُضاف تلقائياً</strong> تفادياً لإنشاء نسخة ثانية من كتابٍ عندك.</div>';
      }
      if (!d.has_boundary) {
        footnotes += '<div class="rs-note text-warning">' +
          '<i class="bi bi-exclamation-triangle" aria-hidden="true"></i><strong>لا يوجد حدّ محفوظ لهذا المصدر</strong> — ' +
          'فلا سبيل لتمييز صفٍّ استجدّ عن صفٍّ قديم لم يُستورد، وعُدَّ <strong>كل</strong> صفّ ' +
          'غير معروف جديداً. راجع القائمة قبل الدمج، والتقط الحدّ بعده بأمر ' +
          '<code>capture_legacy_boundary</code>.</div>';
      }

      if (!t.new) {
        out.innerHTML = alertBox(t.held ? 'warning' : 'info',
          '<strong>لا يوجد أي جديد.</strong> كل صفوف المصدر (' + isoNum(t.rows) +
          ') إمّا موجودة عندك أو موقوفة. لا حاجة لتشغيل الخطوة ٤.' + footnotes);
        setStep(3, 'done');
        return;
      }

      var rows = d.tables.filter(function (x) { return x.rows; }).map(function (x) {
        var hl = x.new ? ' class="is-new"' : '';
        return '<tr' + hl + '><td><code>' + esc(x.table) + '</code></td>' +
               '<td>' + esc(KIND_LABELS[x.kind] || x.kind) + '</td>' +
               '<td class="rs-num">' + isoNum(x.rows) + '</td>' +
               '<td class="rs-num">' + isoNum(x.known) + '</td>' +
               '<td class="rs-num"><strong>' + isoNum(x.new) + '</strong></td>' +
               '<td class="rs-num">' + bytes(x.new_bytes) + '</td>' +
               '<td class="rs-num">' + (x.held ? isoNum(x.held) : '—') + '</td></tr>';
      }).join('');

      out.innerHTML =
        alertBox('warning',
          '<strong>يوجد ' + isoNum(t.new) + ' صفّاً جديداً</strong> لم يدخل نظامك بعد، ' +
          'بمرفقات حجمها ' + bytes(t.new_bytes) + '. الخطوة ٤ ستضيفها.' + footnotes) +
        table('<thead><tr><th scope="col">الجدول</th><th scope="col">النوع</th><th scope="col">صفوف المصدر</th>' +
          '<th scope="col">عندنا</th><th scope="col">جديد</th><th scope="col">حجم مرفقاته</th>' +
          '<th scope="col">موقوف</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>');

      setStep(3, 'done');
      setStep(4, 'active');
    }).catch(function (e) {
      busy(btn, false);
      failure(out, e.message);
    });
  }

  // ── الخطوة ٤: مهمّة الدمج (تعمل خارج المتصفّح) ───────────────────────
  var pollTimer = null;

  // الحالةُ نصٌّ في رقاقةٍ بلون معناها من رموز الهويّة
  var JOB_BADGE = {
    queued:    ['في الانتظار', 'is-wait'],
    running:   ['قيد التنفيذ', 'is-prog'],
    done:      ['اكتملت', 'is-done'],
    failed:    ['فشلت', 'is-late'],
    cancelled: ['أُلغيت', '']
  };

  function jobUrl(tpl, id) { return tpl.replace(/0\/?$/, id + '/'); }

  function renderSummary(s) {
    if (!s) return '';
    var rows = [
      ['books', 'كتاب جديد'], ['updated', 'مُحدَّث'], ['skipped', 'متخطّى'],
      ['held', 'موقوف (لم يُضَف)'], ['files', 'مرفق أُضيف'],
      ['files_non_pdf', 'مرفق غير PDF'], ['file_errors', 'مرفق تعذّر'],
      ['file_unknown_type', 'مرفق بنوع مجهول']
    ].filter(function (p) { return s[p[0]]; })
     .map(function (p) {
       return '<tr><th scope="row">' + p[1] + '</th><td class="rs-num"><strong>' + isoNum(s[p[0]]) + '</strong></td></tr>';
     }).join('');
    var out = rows
      ? table('<tbody>' + rows + '</tbody>')
      : alertBox('info', 'لم يتغيّر شيء — لا صفوف جديدة.');
    var ents = s.created_entities || [];
    if (ents.length) {
      out += '<div class="rs-note"><strong>جهات أُنشئت أثناء الدمج (' + isoNum(ents.length) +
        ') — راجعها تفادياً للتكرار:</strong><div class="text-muted">' +
        ents.slice(0, 40).map(esc).join(' · ') + (ents.length > 40 ? ' …' : '') + '</div></div>';
    }
    return out;
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function pollJob(id) {
    fetch(jobUrl(URLS.job, id), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { $('rsJobPhase').textContent = d.error || 'تعذّر قراءة حالة المهمّة.'; return; }
        paintState(d.state);

        var badge = JOB_BADGE[d.status] || [d.status, ''];
        var st = $('rsJobStatus');
        st.textContent = badge[0];
        st.className = ('rs-chip ' + badge[1]).trim();
        $('rsJobId').textContent = d.id;
        $('rsJobPhase').textContent = d.phase || '…';

        var bar = $('rsJobBar');
        bar.style.width = (d.total ? d.percent : (d.is_live ? 100 : 0)) + '%';
        bar.classList.toggle('progress-bar-striped', d.is_live);
        bar.classList.toggle('progress-bar-animated', d.is_live);
        bar.parentNode.setAttribute('aria-valuenow', d.total ? d.percent : 0);

        $('rsJobSpin').style.display = d.is_live ? '' : 'none';
        $('rsJobCancel').disabled = !d.is_live || d.cancel_requested;

        if (d.is_live) {
          pollTimer = setTimeout(function () { pollJob(id); }, 2000);
          return;
        }

        stopPolling();
        var out = $('rsJobOut');
        if (d.status === 'done') {
          out.innerHTML = alertBox('success', '<strong>اكتمل الدمج.</strong>') + renderSummary(d.summary);
          setStep(4, 'done');
        } else if (d.status === 'cancelled') {
          out.innerHTML = alertBox('warning',
            '<strong>أُلغيت المهمّة.</strong> ما اكتمل قبل الإلغاء محفوظ — أعد التشغيل ليُكمل من حيث توقّف.')
            + renderSummary(d.summary);
        } else {
          out.innerHTML = alertBox('danger',
            '<strong>فشلت المهمّة.</strong><pre class="rs-log">'
            + esc((d.error || '').slice(0, 1200)) + '</pre>');
        }
        $('rsMergeBtn').disabled = false;
      })
      .catch(function () {
        // الخادم قد يكون مشغولاً — نُعيد المحاولة بدل إعلان الفشل
        pollTimer = setTimeout(function () { pollJob(id); }, 4000);
      });
  }

  function watchJob(id) {
    stopPolling();
    $('rsJobPanel').classList.remove('d-none');
    $('rsJobOut').innerHTML = '';
    $('rsMergeBtn').disabled = true;
    pollJob(id);
  }

  function startMerge() {
    var btn = $('rsMergeBtn'), out = $('rsMergeOut');
    var mode = (document.querySelector('#rsMergeForm input[name="merge_mode"]:checked') || {}).value
               || 'skip_existing';
    var warn = mode === 'update_existing'
      ? 'وضع «تحديث الموجود» سيستبدل حقول كتب موجودة بما في المصدر.\n\n' : '';
    ask({
      title: 'بدء الدمج',
      message: warn + 'سيعمل خارج المتصفّح — يمكنك إغلاق الصفحة والعودة لمتابعته.',
      okText: 'ابدأ الدمج',
      danger: mode === 'update_existing'
    }).then(function (ok) { if (ok) runMerge(btn, out, mode); });
  }

  function runMerge(btn, out, mode) {
    busy(btn, true, 'جارٍ البدء…');
    out.innerHTML = '';
    post(URLS.start, {
      merge_mode: mode,
      restore_files: $('rsFiles').checked ? 'on' : '',
      include_held: ''
    }).then(function (d) {
      busy(btn, false);
      if (!d.ok) {
        out.innerHTML = alertBox('warning', esc(d.error));
        if (d.job_id) watchJob(d.job_id);
        return;
      }
      watchJob(d.job_id);
    }).catch(function (e) {
      busy(btn, false);
      failure(out, e.message);
    });
  }

  function cancelJob() {
    var id = $('rsJobId').textContent;
    if (!id || id === '—') return;
    ask({
      title: 'إلغاء المهمّة',
      message: 'ما اكتمل يبقى محفوظاً، والإلغاء يقع بين الدفعات فلا يُترك مرفقٌ ناقص.',
      okText: 'اطلب الإلغاء'
    }).then(function (ok) {
      if (!ok) return;
      $('rsJobCancel').disabled = true;
      fetch(jobUrl(URLS.jobCancel, id), {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
      }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        $('rsJobPhase').textContent = 'طُلب الإلغاء — ينتهي عند حدّ الدفعة الحالية…';
      }).catch(function () {
        // كان يفشل صامتاً والزرُّ معطّلٌ إلى الأبد
        $('rsJobCancel').disabled = false;
        $('rsJobPhase').textContent = 'تعذّر إرسال طلب الإلغاء — أعد المحاولة.';
      });
    });
  }

  // ── متصفّح ملفات الباكاب ─────────────────────────────────────────────
  // كلُّ مجلّدٍ وملفٍّ زرٌّ (كانت ‎div‎ بنقرٍ وحده فلا تُبلَغ بلوحة المفاتيح)
  function initBrowser() {
    var modal = $('bakBrowseModal');
    if (!modal) return;
    var listEl = $('bakBrowseList'), curEl = $('bakCurPath'), quickEl = $('bakQuick'),
        upBtn = $('bakUpBtn'), pathInput = $('bakPathInput');
    var parentPath = null;

    function fmtMB(mb) { return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb.toFixed(1) + ' MB'; }

    function load(path) {
      listEl.innerHTML = '<div class="rs-empty" role="status"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span>جارٍ التحميل…</div>';
      quickEl.innerHTML = '';
      fetch(URLS.browse + '?path=' + encodeURIComponent(path || ''),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) { listEl.innerHTML = '<div class="rs-empty is-error" role="alert">' + esc(data.error) + '</div>'; return; }
          curEl.value = data.path || '';
          parentPath = data.parent;
          upBtn.disabled = (data.parent === null || data.parent === undefined);
          if (data.quick && data.quick.length) {
            quickEl.innerHTML = '<span class="rs-label">وصول سريع:</span>' +
              data.quick.map(function (q) {
                return '<button type="button" class="rs-quick bak-nav" data-path="' + esc(q) + '">' +
                  '<i class="bi bi-star-fill" aria-hidden="true"></i><bdi>' + esc(q) + '</bdi></button>';
              }).join('');
          }
          var html = '';
          (data.dirs || []).forEach(function (dname) {
            var full = data.is_root ? dname : (String(data.path).replace(/[\\/]$/, '') + '\\' + dname);
            html += '<button type="button" class="rs-entry bak-nav" data-path="' + esc(full) + '">' +
              '<i class="bi bi-folder-fill is-dir" aria-hidden="true"></i>' +
              '<span class="visually-hidden">مجلّد: </span><bdi class="rs-entry__name">' + esc(dname) + '</bdi></button>';
          });
          (data.files || []).forEach(function (f) {
            var full = String(data.path).replace(/[\\/]$/, '') + '\\' + f.name;
            html += '<button type="button" class="rs-entry bak-pick" data-path="' + esc(full) + '">' +
              '<i class="bi bi-file-earmark-zip is-file" aria-hidden="true"></i>' +
              '<span class="visually-hidden">ملفّ باكاب: </span><bdi class="rs-entry__name">' + esc(f.name) + '</bdi>' +
              '<bdi dir="ltr" class="rs-entry__size">' + fmtMB(f.size_mb) + '</bdi></button>';
          });
          if (!html) html = '<div class="rs-empty">لا توجد مجلدات فرعية ولا ملفات باكاب هنا.</div>';
          listEl.innerHTML = html;
        })
        .catch(function () { listEl.innerHTML = '<div class="rs-empty is-error" role="alert">تعذّر التحميل.</div>'; });
    }

    listEl.addEventListener('click', function (e) {
      var nav = e.target.closest('.bak-nav');
      if (nav) { load(nav.dataset.path); return; }
      var pick = e.target.closest('.bak-pick');
      if (pick) {
        pathInput.value = pick.dataset.path;
        var inst = window.bootstrap && bootstrap.Modal.getInstance(modal);
        if (inst) inst.hide();
      }
    });
    quickEl.addEventListener('click', function (e) {
      var nav = e.target.closest('.bak-nav');
      if (nav) load(nav.dataset.path);
    });
    upBtn.addEventListener('click', function () {
      if (parentPath !== null && parentPath !== undefined) load(parentPath);
    });
    modal.addEventListener('shown.bs.modal', function () {
      var cur = pathInput.value.trim();
      load(cur ? cur.replace(/[\\/][^\\/]*$/, '') : '');
    });
  }

  // ── الإقلاع ──────────────────────────────────────────────────────────
  function init() {
    URLS = window.RESTORE_URLS || {};
    if (!$('rsProbeBtn')) return;

    $('rsProbeBtn').addEventListener('click', probe);
    $('rsReconcilePreview').addEventListener('click', function () { reconcile(false); });
    $('rsReconcileApply').addEventListener('click', function () { reconcile(true); });
    $('rsDeltaBtn').addEventListener('click', delta);
    $('rsMergeBtn').addEventListener('click', startMerge);
    $('rsJobCancel').addEventListener('click', cancelJob);
    initBrowser();
    syncTrack();

    // مهمّة كانت تعمل قبل فتح الصفحة (أو قبل إغلاقها) — نلتقطها ونتابعها
    if (window.RESTORE_LIVE_JOB) {
      setStep(4, 'active');
      watchJob(window.RESTORE_LIVE_JOB);
    }
  }

  window.RestoreWizard = { init: init };
})();
