/* ============================================================
   data_restore.js — معالج صفحة دمج البيانات من النظام القديم.

   المبدأ: كل نداء هنا قراءةٌ رخيصة أو معاينة. الكتابة الوحيدة هي
   «اعتماد الربط» (يكتب حقل مرجع المصدر فقط) و«الدمج» (نموذج POST عادي).
   الرسائل صادقة: صفر نتائج تُعرَض كصفر، لا كنجاح.
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

  function bytes(b) {
    if (!b) return '—';
    var u = ['بايت', 'ك.ب', 'م.ب', 'ج.ب'], i = 0, v = Number(b);
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toFixed(i ? 1 : 0) + ' ' + u[i];
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
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>' + (label || 'جارٍ التنفيذ…');
    } else {
      btn.disabled = false;
      if (btn.dataset.html) btn.innerHTML = btn.dataset.html;
    }
  }

  function alertBox(kind, html) {
    return '<div class="alert alert-' + kind + ' py-2 mb-0 small">' + html + '</div>';
  }

  function setStep(n, state) {
    var el = document.querySelector('.rs-step[data-step="' + n + '"]');
    if (el) el.setAttribute('data-state', state);
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
      '<div class="mt-1" style="font-size:.75rem;">تحقّق من اسم الخادم وقاعدة البيانات وكلمة السر، ' +
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
               '<td class="rs-num">' + num(t.rows) + '</td>' +
               '<td class="rs-num">' + num(t.with_file) + '</td></tr>';
      }).join('');

      out.innerHTML =
        alertBox('success', '<strong>الاتصال ناجح.</strong> ' + num(d.tables.length) +
          ' جدولاً، ' + num(d.total_rows) + ' سجلاً، السنوات: ' + esc(d.years.join('، ')) + '.') +
        '<div class="table-responsive mt-2"><table class="table table-sm rs-table mb-0">' +
        '<thead><tr><th>الجدول</th><th>النوع</th><th>الصفوف</th><th>بمرفق</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div>';

      setStep(1, 'done');
      setStep(2, 'active');
      setStep(3, 'active');
    }).catch(function (e) {
      busy(btn, false);
      failure(out, e.message);
    });
  }

  // ── الخطوة ٢: المطابقة ───────────────────────────────────────────────
  function reconcile(apply) {
    var btn = apply ? $('rsReconcileApply') : $('rsReconcilePreview');
    var out = $('rsReconcileOut');
    if (apply && !confirm('اعتماد الربط؟\n\nسيُكتب حقل «مرجع المصدر» فقط على الكتب المُطابَقة. ' +
                          'لا يتغيّر أي رقم أو عنوان أو مرفق.')) return;
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
            ? '<div class="text-danger mt-1">تحقّق البصمات: ' + num(d.verify_mismatches.length) +
              ' اختلافاً من ' + num(d.verified_bytes) + ' — لم يُعتمد شيء.</div>'
            : '<div class="text-success mt-1"><i class="bi bi-shield-check me-1"></i>تحقّق البصمات: ' +
              num(d.verified_bytes) + ' مرفقاً من <strong>مطابقات الحجم</strong> قُورنت — تطابق تامّ.</div>';
        }
        var attn = (d.attention || []).length;
        if (attn) {
          verifyLine += '<div class="text-warning-emphasis mt-1">' +
            '<i class="bi bi-eye me-1"></i><strong>' + num(attn) + '</strong> كتاباً رُبط بالعنوان والتاريخ ' +
            'لا بحجم المرفق — الفارق طبيعي إن استبدلتَ المرفق داخل التطبيق، وإلا فراجعها.</div>';
        }

        var body =
          '<table class="table table-sm rs-table mb-0"><tbody>' +
          '<tr><td>صفوف المصدر</td><td class="rs-num fw-bold">' + num(d.source_rows) + '</td></tr>' +
          '<tr><td>كتب بلا ربط قبل التشغيل</td><td class="rs-num">' + num(d.books_without_ref) + '</td></tr>' +
          '<tr><td>مُطابَقة بمفتاح فريد</td><td class="rs-num fw-bold text-success">' + num(d.matched) + '</td></tr>' +
          '<tr><td class="ps-4 text-muted">منها بحجم المرفق</td><td class="rs-num">' + num(d.matched_by_size) + '</td></tr>' +
          '<tr><td class="ps-4 text-muted">منها بالعنوان والتاريخ</td><td class="rs-num">' + num(d.matched_by_title) + '</td></tr>' +
          '<tr><td>ملتبسة (تُركت دون ربط)</td><td class="rs-num">' + num(d.ambiguous) + '</td></tr>' +
          '<tr><td>كتب بلا مطابقة (كتبك غالباً)</td><td class="rs-num">' + num(d.unmatched_books) + '</td></tr>' +
          '<tr><td>صفوف مصدر بلا مطالبة</td><td class="rs-num">' + num(d.unclaimed_source_rows) + '</td></tr>' +
          '</tbody></table>';

        if (d.applied) {
          out.innerHTML = alertBox('success',
            '<strong>تمّ الربط.</strong> خُتم «مرجع المصدر» على ' + num(d.matched) + ' كتاباً.' + verifyLine) + body;
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
            '<strong>معاينة — لم يُكتب شيء.</strong> سيُربط ' + num(d.matched) +
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
        footnotes += '<div class="mt-1" style="font-size:.75rem;">لديك ' + num(t.app_only) +
          ' كتاباً لا وجود له في المصدر — أدخلتَها داخل التطبيق، ولن يمسّها الدمج.</div>';
      }
      if (t.held) {
        footnotes += '<div class="mt-1" style="font-size:.75rem;">' +
          '<i class="bi bi-pause-circle me-1"></i><strong>' + num(t.held) + ' صفّاً موقوفاً:</strong> ' +
          'كان موجوداً في المصدر قبل آخر مزامنة ولم يُستورد — غالباً تعميم مكرّر تُرك عمداً. ' +
          '<strong>لا يُضاف تلقائياً</strong> تفادياً لإنشاء نسخة ثانية من كتابٍ عندك.</div>';
      }
      if (!d.has_boundary) {
        footnotes += '<div class="mt-1 text-warning" style="font-size:.75rem;">' +
          '<i class="bi bi-exclamation-triangle me-1"></i><strong>لا يوجد حدّ محفوظ لهذا المصدر</strong> — ' +
          'فلا سبيل لتمييز صفٍّ استجدّ عن صفٍّ قديم لم يُستورد، وعُدَّ <strong>كل</strong> صفّ ' +
          'غير معروف جديداً. راجع القائمة قبل الدمج، والتقط الحدّ بعده بأمر ' +
          '<code>capture_legacy_boundary</code>.</div>';
      }

      if (!t.new) {
        out.innerHTML = alertBox(t.held ? 'warning' : 'info',
          '<strong>لا يوجد أي جديد.</strong> كل صفوف المصدر (' + num(t.rows) +
          ') إمّا موجودة عندك أو موقوفة. لا حاجة لتشغيل الخطوة ٤.' + footnotes);
        setStep(3, 'done');
        return;
      }

      var rows = d.tables.filter(function (x) { return x.rows; }).map(function (x) {
        var hl = x.new ? ' class="table-warning"' : '';
        return '<tr' + hl + '><td><code>' + esc(x.table) + '</code></td>' +
               '<td>' + esc(KIND_LABELS[x.kind] || x.kind) + '</td>' +
               '<td class="rs-num">' + num(x.rows) + '</td>' +
               '<td class="rs-num">' + num(x.known) + '</td>' +
               '<td class="rs-num fw-bold">' + num(x.new) + '</td>' +
               '<td class="rs-num">' + bytes(x.new_bytes) + '</td>' +
               '<td class="rs-num">' + (x.held ? num(x.held) : '—') + '</td></tr>';
      }).join('');

      out.innerHTML =
        alertBox('warning',
          '<strong>يوجد ' + num(t.new) + ' صفّاً جديداً</strong> لم يدخل نظامك بعد، ' +
          'بمرفقات حجمها ' + bytes(t.new_bytes) + '. الخطوة ٤ ستضيفها.' + footnotes) +
        '<div class="table-responsive mt-2"><table class="table table-sm rs-table mb-0">' +
        '<thead><tr><th>الجدول</th><th>النوع</th><th>صفوف المصدر</th><th>عندنا</th>' +
        '<th>جديد</th><th>حجم مرفقاته</th><th>موقوف</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div>';

      setStep(3, 'done');
      setStep(4, 'active');
    }).catch(function (e) {
      busy(btn, false);
      failure(out, e.message);
    });
  }

  // ── الخطوة ٤: مهمّة الدمج (تعمل خارج المتصفّح) ───────────────────────
  var pollTimer = null;

  var JOB_BADGE = {
    queued:    ['في الانتظار', 'text-bg-secondary'],
    running:   ['قيد التنفيذ', 'text-bg-primary'],
    done:      ['اكتملت', 'text-bg-success'],
    failed:    ['فشلت', 'text-bg-danger'],
    cancelled: ['أُلغيت', 'text-bg-warning']
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
       return '<tr><td>' + p[1] + '</td><td class="rs-num fw-bold">' + num(s[p[0]]) + '</td></tr>';
     }).join('');
    var out = rows
      ? '<table class="table table-sm rs-table mb-0"><tbody>' + rows + '</tbody></table>'
      : alertBox('info', 'لم يتغيّر شيء — لا صفوف جديدة.');
    var ents = s.created_entities || [];
    if (ents.length) {
      out += '<div class="mt-2 small"><strong>جهات أُنشئت أثناء الدمج (' + num(ents.length) +
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

        var badge = JOB_BADGE[d.status] || [d.status, 'text-bg-secondary'];
        var st = $('rsJobStatus');
        st.textContent = badge[0];
        st.className = 'badge ' + badge[1];
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
            '<strong>فشلت المهمّة.</strong><pre class="mb-0 mt-1" style="white-space:pre-wrap; font-size:.72rem;">'
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
      ? '\n\nوضع «تحديث الموجود» سيستبدل حقول كتب موجودة بما في المصدر.' : '';
    if (!confirm('تأكيد بدء الدمج؟' + warn +
                 '\n\nسيعمل خارج المتصفّح — يمكنك إغلاق الصفحة والعودة لمتابعته.')) return;

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
    if (!confirm('طلب إلغاء المهمّة؟\n\nما اكتمل يبقى محفوظاً، والإلغاء يقع بين الدفعات فلا يُترك مرفقٌ ناقص.')) return;
    $('rsJobCancel').disabled = true;
    fetch(jobUrl(URLS.jobCancel, id), {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function () { $('rsJobPhase').textContent = 'طُلب الإلغاء — ينتهي عند حدّ الدفعة الحالية…'; });
  }

  // ── متصفّح ملفات الباكاب ─────────────────────────────────────────────
  function initBrowser() {
    var modal = $('bakBrowseModal');
    if (!modal) return;
    var listEl = $('bakBrowseList'), curEl = $('bakCurPath'), quickEl = $('bakQuick'),
        upBtn = $('bakUpBtn'), pathInput = $('bakPathInput');
    var parentPath = null;

    function fmtMB(mb) { return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb.toFixed(1) + ' MB'; }

    function load(path) {
      listEl.innerHTML = '<div class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2"></span>جارٍ التحميل...</div>';
      quickEl.innerHTML = '';
      fetch(URLS.browse + '?path=' + encodeURIComponent(path || ''),
            { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) { listEl.innerHTML = '<div class="text-danger p-3 small">' + esc(data.error) + '</div>'; return; }
          curEl.value = data.path || '';
          parentPath = data.parent;
          upBtn.disabled = (data.parent === null || data.parent === undefined);
          if (data.quick && data.quick.length) {
            quickEl.innerHTML = '<div class="small text-muted mb-1">وصول سريع:</div>' +
              data.quick.map(function (q) {
                return '<button type="button" class="btn btn-sm btn-light border me-1 mb-1 bak-nav" data-path="' +
                  esc(q) + '"><i class="bi bi-star me-1 text-warning"></i>' + esc(q) + '</button>';
              }).join('');
          }
          var html = '';
          (data.dirs || []).forEach(function (dname) {
            var full = data.is_root ? dname : (String(data.path).replace(/[\\/]$/, '') + '\\' + dname);
            html += '<div class="d-flex align-items-center px-3 py-1 border-bottom bak-nav" style="cursor:pointer;" data-path="' +
              esc(full) + '"><i class="bi bi-folder-fill text-warning me-2"></i><span>' + esc(dname) + '</span></div>';
          });
          (data.files || []).forEach(function (f) {
            var full = String(data.path).replace(/[\\/]$/, '') + '\\' + f.name;
            html += '<div class="d-flex align-items-center justify-content-between px-3 py-1 border-bottom bak-pick" style="cursor:pointer;" data-path="' +
              esc(full) + '"><span><i class="bi bi-file-earmark-zip text-success me-2"></i>' + esc(f.name) +
              '</span><span class="text-muted small">' + fmtMB(f.size_mb) + '</span></div>';
          });
          if (!html) html = '<div class="text-muted p-3 small">لا توجد مجلدات فرعية ولا ملفات باكاب هنا.</div>';
          listEl.innerHTML = html;
        })
        .catch(function () { listEl.innerHTML = '<div class="text-danger p-3 small">تعذّر التحميل.</div>'; });
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

    // مهمّة كانت تعمل قبل فتح الصفحة (أو قبل إغلاقها) — نلتقطها ونتابعها
    if (window.RESTORE_LIVE_JOB) {
      setStep(4, 'active');
      watchJob(window.RESTORE_LIVE_JOB);
    }
  }

  window.RestoreWizard = { init: init };
})();
