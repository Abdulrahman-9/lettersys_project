(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const pageRoot = document.getElementById("bookUnifiedPage");
    const bulkBar = document.getElementById("bulkActionsBar");
    const countEl = document.getElementById("bulkSelectedCount");
    const selectAll = document.getElementById("selectAllBooks");
    const clearBtn = document.getElementById("bulkClearBtn");
    const bulkDeleteBtn = document.getElementById("bulkDeleteBtn");
    const bulkUpdateStatusBtn = document.getElementById("bulkUpdateStatusBtn");
    const confirmBulkUpdateBtn = document.getElementById("confirmBulkUpdateBtn");
    const bulkStatusSelect = document.getElementById("bulkStatusSelect");
    const bulkUpdateCount = document.getElementById("bulkUpdateCount");
    const bulkUpdateModalEl = document.getElementById("bulkUpdateModal");
    const liveRegion = document.getElementById("bookUnifiedLiveRegion");

    function getCsrfToken() {
      const value = `; ${document.cookie}`;
      const parts = value.split("; csrftoken=");
      if (parts.length === 2) {
        return parts.pop().split(";").shift() || "";
      }
      return "";
    }

    function getSelectedBookIds() {
      const rawIds = Array.from(document.querySelectorAll(".row-checkbox:checked"))
        .map(function (cb) {
          return cb.value;
        })
        .filter(Boolean);
      return Array.from(new Set(rawIds));
    }

    // النتيجةُ تُرى وتُسمَع: كانت تُكتب في منطقةٍ مخفيّة لقارئ الشاشة وحدَه، فلا يرى
    // المبصرُ تأكيداً ولا خطأً (تدقيقُ نيلسن 2026‑10‑07، A#7).
    function announceMessage(message, level) {
      if (liveRegion) liveRegion.textContent = message;
      if (window.ToastCenter && typeof window.ToastCenter.show === "function") {
        window.ToastCenter.show(level || "info", message);
      }
    }

    // الجماعيُّ يُرسل ويعرض ما يقوله الخادم — والقائمةُ تُعاد منه لا تُخمَّن.
    // (كانت الواجهةُ تمحو كلَّ المحدَّد وتكتب حالتَه الجديدة ولو رفض الخادمُ بعضَه:
    //  كتابٌ ليس لقسمك يختفي من الشاشة ويبقى في القاعدة — تدقيقُ 2026‑10‑08.)
    async function postBulk(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(body),
      });
      // ردٌّ ليس JSON (صفحةُ خطأٍ أو انتهاءُ الجلسة) لا يصير «Unexpected token <»
      const payload = await response.json().catch(function () { return {}; });
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || payload.message
          || (response.status === 403 ? "لا تملك هذا الإجراء." : "تعذّر التنفيذ — أعد المحاولة."));
      }
      return payload;
    }

    async function reloadList(emptiedThePage) {
      const mgr = window.bookAjaxManager;
      if (!mgr || typeof mgr.updateUrlAndLoadData !== "function") {
        window.location.reload();
        return;
      }
      // أُفرغت الصفحةُ الأخيرة ⟵ السابقة، لا «صفحة 3 من 2»
      if (emptiedThePage && mgr.currentState && mgr.currentState.page > 1) mgr.currentState.page -= 1;
      await mgr.updateUrlAndLoadData();
      refreshSelection();
    }

    function refreshSelection() {
      const rows = document.querySelectorAll(".row-checkbox");
      const checkedRows = document.querySelectorAll(".row-checkbox:checked");
      const checked = checkedRows.length;
      if (countEl) countEl.textContent = String(checked);
      if (bulkBar) bulkBar.style.display = checked > 0 ? "block" : "none";
      if (liveRegion) {
        liveRegion.textContent = checked > 0 ? "تم تحديد " + checked + " كتاب" : "تم إلغاء جميع التحديدات";
      }

      if (selectAll) {
        selectAll.checked = rows.length > 0 && checked === rows.length;
        selectAll.indeterminate = checked > 0 && checked < rows.length;
      }
    }

    function clearSelection() {
      document.querySelectorAll(".row-checkbox").forEach(function (cb) {
        cb.checked = false;
      });
      if (selectAll) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
      }
      refreshSelection();
    }

    if (selectAll) {
      selectAll.addEventListener("change", function () {
        document.querySelectorAll(".row-checkbox").forEach(function (cb) {
          cb.checked = selectAll.checked;
        });
        refreshSelection();
      });
    }

    document.addEventListener("change", function (e) {
      if (e.target && e.target.classList.contains("row-checkbox")) {
        refreshSelection();
      }
    });

    if (clearBtn) clearBtn.addEventListener("click", clearSelection);

    if (bulkDeleteBtn) {
      bulkDeleteBtn.addEventListener("click", async function () {
        const selectedIds = getSelectedBookIds();
        if (selectedIds.length === 0) return;

        const deleteUrl = pageRoot ? pageRoot.getAttribute("data-bulk-delete-url") : "";
        if (!deleteUrl) return;

        const ok = await window.confirmDelete({
          title: "نقل إلى السلّة",
          message: "نقل الكتب المحدّدة (" + selectedIds.length + ") إلى السلّة؟ تُستعاد منها لاحقاً.",
          okText: "انقل إلى السلّة",
        });
        if (!ok) return;

        // الصفُّ وبطاقةُ الجوال يحملان المعرّفَ نفسَه — فالعدُّ على القيم لا الخانات
        const onPage = new Set(Array.from(document.querySelectorAll(".row-checkbox")).map(function (cb) { return cb.value; }));
        const emptied = selectedIds.length >= onPage.size;
        bulkDeleteBtn.disabled = true;
        try {
          const payload = await postBulk(deleteUrl, { book_ids: selectedIds });
          const partial = payload.deleted_count < selectedIds.length;
          announceMessage(payload.message, partial ? "warning" : "success");
          await reloadList(emptied && !partial);
        } catch (error) {
          announceMessage(error.message, "error");
        } finally {
          bulkDeleteBtn.disabled = false;
        }
      });
    }

    if (bulkUpdateStatusBtn) {
      bulkUpdateStatusBtn.addEventListener("click", function () {
        const selectedIds = getSelectedBookIds();
        if (selectedIds.length === 0) return;

        if (bulkUpdateCount) {
          bulkUpdateCount.textContent = String(selectedIds.length);
        }

        if (bulkStatusSelect) {
          bulkStatusSelect.value = "";
        }

        if (bulkUpdateModalEl && window.bootstrap && window.bootstrap.Modal) {
          const modal = window.bootstrap.Modal.getOrCreateInstance(bulkUpdateModalEl);
          modal.show();
        }
      });
    }

    if (confirmBulkUpdateBtn) {
      confirmBulkUpdateBtn.addEventListener("click", async function () {
        const selectedIds = getSelectedBookIds();
        const status = bulkStatusSelect ? bulkStatusSelect.value : "";

        if (selectedIds.length === 0) return;
        if (!status) {
          announceMessage("اختر الإجراءَ أوّلاً: إنهاء المتابعة أو إعادة فتحها.", "warning");
          if (bulkStatusSelect) bulkStatusSelect.focus();
          return;
        }

        const statusUrl = pageRoot ? pageRoot.getAttribute("data-bulk-status-url") : "";
        if (!statusUrl) return;

        confirmBulkUpdateBtn.disabled = true;
        try {
          const payload = await postBulk(statusUrl, { book_ids: selectedIds, status: status });
          const partial = payload.updated_count < selectedIds.length;
          announceMessage(payload.message, partial ? "warning" : "success");
          if (bulkUpdateModalEl && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(bulkUpdateModalEl).hide();
          }
          await reloadList(false);
        } catch (error) {
          announceMessage(error.message, "error");
        } finally {
          confirmBulkUpdateBtn.disabled = false;
        }
      });
    }

    // Esc يُلغي التحديد — إلّا وهو يُغلق حواريّةً أو يمسح حقلاً: كان يُسقط التحديدَ
    // مع إغلاق نافذة «تحديث الحالة» ومع «مسح (Esc)» في البحث.
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (document.querySelector(".modal.show")) return;
      const active = document.activeElement;
      if (active && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName) && !active.classList.contains("row-checkbox")) return;
      if (document.querySelectorAll(".row-checkbox:checked").length === 0) return;
      clearSelection();
    });

    refreshSelection();

    // ── طباعة ──────────────────────────────────────────────────────────────
    const printBtn = document.getElementById('printTableBtn');
    if (printBtn) {
      printBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.print();
      });
    }

    // ── تصدير CSV ──────────────────────────────────────────────────────────
    const csvBtn = document.getElementById('exportCsvBtn');
    if (csvBtn) {
      csvBtn.addEventListener('click', function (e) {
        e.preventDefault();
        const params = new URLSearchParams(window.location.search);
        window.location.href = '/books/api/unified/export/csv/?' + params.toString();
      });
    }

    // ── تبديل رؤية الأعمدة ─────────────────────────────────────────────────
    document.querySelectorAll('.column-toggle').forEach(function (cb) {
      cb.addEventListener('change', function () {
        const col = this.dataset.column;
        document.querySelectorAll('.col-' + col).forEach(function (el) {
          el.classList.toggle('d-none', !cb.checked);
        });
      });
    });
  });
})();
