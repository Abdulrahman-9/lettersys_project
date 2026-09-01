(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function getCsrfToken() {
    return getCookie("csrftoken");
  }

  function announce(message) {
    const liveRegion = document.getElementById("bookUnifiedLiveRegion");
    if (liveRegion) {
      liveRegion.textContent = message;
    }
  }

  function showToast(message, level) {
    if (window.loggingSystem && typeof window.loggingSystem.logInfo === "function") {
      window.loggingSystem.logInfo("book_unified", `${level || "info"}: ${message}`);
    }
    announce(message);

    if (window.ToastCenter && typeof window.ToastCenter.show === "function") {
      const normalizedLevel = level === "danger" ? "error" : (level || "info");
      window.ToastCenter.show(normalizedLevel, message, {
        title: normalizedLevel === "success" ? "تمت العملية" : (normalizedLevel === "error" ? "تعذر إكمال العملية" : "معلومة"),
      });
    }
  }

  function getCurrentPageNumber() {
    const params = new URLSearchParams(window.location.search);
    const page = parseInt(params.get("page") || "1", 10);
    return Number.isNaN(page) || page < 1 ? 1 : page;
  }

  function navigateToPage(pageNumber) {
    const params = new URLSearchParams(window.location.search);
    if (pageNumber > 1) {
      params.set("page", String(pageNumber));
    } else {
      params.delete("page");
    }
    const query = params.toString();
    window.location.href = `${window.location.pathname}${query ? `?${query}` : ""}`;
  }

  function removeBookFromAllViews(bookId) {
    if (!bookId) return;
    document
      .querySelectorAll(`tr.book-row[data-book-id="${bookId}"], .book-card[data-book-id="${bookId}"]`)
      .forEach(function (el) {
        el.remove();
      });
  }

  function getRemainingVisibleBooksCount() {
    // صفوف سطح المكتب هي مصدر الحقيقة لعدّ هذه الصفحة (الجوال يُعاد تحميله خادمياً عند التنقّل).
    return document.querySelectorAll("tr.book-row").length;
  }

  function showEmptyStateInline() {
    const emptyState = document.getElementById("emptyState");
    const desktopContainer = document.getElementById("desktopTableContainer");
    const mobileContainer = document.getElementById("mobileCardsContainer");
    const paginationContainer = document.getElementById("paginationContainer");

    if (desktopContainer) desktopContainer.style.display = "none";
    if (mobileContainer) mobileContainer.style.display = "none";
    if (paginationContainer) paginationContainer.style.display = "none";
    if (emptyState) emptyState.style.display = "block";
  }

  function handlePaginationEdgeAfterDelete() {
    const remainingBooks = getRemainingVisibleBooksCount();
    if (remainingBooks > 0) {
      return;
    }

    const currentPage = getCurrentPageNumber();
    if (currentPage > 1) {
      navigateToPage(currentPage - 1);
      return;
    }

    showEmptyStateInline();
  }

  // شارات الحالة الحيّة (book_unified_filter_bar.html) — مفتاحها حالة المتابعة
  const PILL_BY_STATE = {
    pending:   "pill-count-pending",
    due_today: "pill-count-due-today",
    overdue:   "pill-count-overdue",
    archived:  "pill-count-archived",
  };

  function _decrement(id) {
    const el = document.getElementById(id);
    if (el && el.textContent) {
      el.textContent = Math.max(0, parseInt(el.textContent, 10) - 1);
    }
  }

  function updateStatsAfterDelete(bookRow) {
    // تحديث DOM فقط: أنقص إجمالي الترقيم + شارة الحالة المطابقة للصف المحذوف.
    _decrement("paginationTotal");

    const state = bookRow.getAttribute("data-followup-state") || bookRow.getAttribute("data-status") || "";
    if (PILL_BY_STATE[state]) _decrement(PILL_BY_STATE[state]);

    // تحديث نطاق الترقيم (from/to)
    const paginationFromEl = document.getElementById("paginationFrom");
    const paginationToEl = document.getElementById("paginationTo");
    if (paginationToEl && paginationToEl.textContent) {
      const newTo = Math.max(0, parseInt(paginationToEl.textContent, 10) - 1);
      paginationToEl.textContent = newTo;
      if (paginationFromEl && paginationFromEl.textContent) {
        if (newTo === 0) paginationFromEl.textContent = 0;
        else if (parseInt(paginationFromEl.textContent, 10) > newTo) paginationFromEl.textContent = newTo;
      }
    }
  }

  // حارس متزامن: يُعيد true/false فوراً ليعرف موجّه النقر هل التُقطت النقرة.
  // العمل الشبكي يُنفَّذ في performDelete (async) دون انتظار — وإلا لأعادت الدالة Promise
  // (truthy دائماً) فيتوقّف الموجّه عند كل نقرة ولا يصل لشارة الحالة/إغلاق الـ popover.
  function handleDeleteClick(target) {
    const trigger = target.closest(".btn-delete, .btn-delete-mobile");
    if (!trigger) return false;

    const deleteUrl = trigger.getAttribute("data-delete-url");
    const bookRow = trigger.closest("tr, .book-card");
    const bookId = trigger.getAttribute("data-book-id") || (bookRow ? bookRow.getAttribute("data-book-id") : "");
    if (!deleteUrl || !bookRow) return true;

    const bookNumber = trigger.getAttribute("data-book-number") || "";
    const confirmed = window.confirm(`تأكيد حذف الكتاب ${bookNumber}؟ سيتم نقله إلى السلة.`);
    if (!confirmed) return true;

    performDelete(trigger, deleteUrl, bookRow, bookId);
    return true;
  }

  async function performDelete(trigger, deleteUrl, bookRow, bookId) {
    trigger.disabled = true;

    try {
      const response = await fetch(deleteUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "فشل الحذف");
      }

      // ✅ Smart update: update counters before removing row
      updateStatsAfterDelete(bookRow);
      
      // Remove the row from DOM with fade animation
      bookRow.style.opacity = "0";
      bookRow.style.transition = "opacity 0.3s ease-in-out";
      setTimeout(function () {
        removeBookFromAllViews(bookId);
        handlePaginationEdgeAfterDelete();
      }, 300);

      showToast(payload.message || "تم حذف الكتاب", "success");
    } catch (error) {
      showToast(error.message || "حدث خطأ أثناء الحذف", "error");
      trigger.disabled = false;
    }
  }

  // الحالات الأربع الموحَّدة (مصدر واحد) — تطابق Book.FOLLOWUP_STATE_CHOICES
  const STATE_DISPLAY = {
    pending:   { label: "قيد المتابعة", icon: "bi-clock-history" },
    due_today: { label: "مستحق اليوم",  icon: "bi-calendar-event-fill" },
    overdue:   { label: "متأخر",         icon: "bi-exclamation-triangle-fill" },
    archived:  { label: "مؤرشف",         icon: "bi-archive-fill" },
  };

  function closeStatusPopover() {
    document.querySelectorAll(".status-popover").forEach(function (p) { p.remove(); });
  }

  function openStatusPopover(badge) {
    closeStatusPopover();
    const current = badge.getAttribute("data-current-status");
    const hasDueDate = badge.getAttribute("data-has-due-date") === "1";

    // إجراءان فقط: أرشفة أو إعادة فتح (الحالات الزمنية الثلاث محسوبة من due_date)
    const actions = [];
    if (current !== "archived") {
      actions.push({ value: "archived", label: "إنهاء المتابعة (أرشفة)", icon: "bi-archive-fill" });
    } else if (hasDueDate) {
      actions.push({ value: "reopen", label: "إعادة فتح المتابعة", icon: "bi-arrow-counterclockwise" });
    } else {
      actions.push({
        value: "_disabled",
        label: "حدّد تاريخاً للمتابعة من صفحة التعديل",
        icon: "bi-info-circle",
        disabled: true,
      });
    }

    const popover = document.createElement("div");
    popover.className = "status-popover";
    actions.forEach(function (opt) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "status-popover-item";
      if (opt.disabled) {
        btn.classList.add("disabled");
        btn.disabled = true;
      }
      btn.setAttribute("data-status", opt.value);
      btn.innerHTML = `<i class="bi ${opt.icon}"></i><span>${opt.label}</span>`;
      if (!opt.disabled) {
        btn.addEventListener("click", function () {
          applyStatusChange(badge, opt.value);
          closeStatusPopover();
        });
      }
      popover.appendChild(btn);
    });

    document.body.appendChild(popover);
    const rect = badge.getBoundingClientRect();
    popover.style.top = (rect.bottom + window.scrollY + 4) + "px";
    popover.style.left = (rect.left + window.scrollX) + "px";
  }

  async function applyStatusChange(badge, action) {
    const statusUrl = badge.getAttribute("data-status-url");
    if (!statusUrl || !action || action === "_disabled") return;

    badge.disabled = true;
    try {
      const body = new URLSearchParams();
      body.append("status", action);   // 'archived' أو 'reopen'
      const response = await fetch(statusUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        body: body.toString(),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "فشل تحديث الحالة");
      }

      syncRowStatus(badge.getAttribute("data-book-id"), payload.followup_state);
      showToast(payload.message || "تم تحديث الحالة", "success");
    } catch (error) {
      showToast(error.message || "حدث خطأ أثناء تحديث الحالة", "error");
    } finally {
      badge.disabled = false;
    }
  }

  // إعادة رسم شارة الحالة لكل صف/بطاقة تخصّ نفس الكتاب (تُستخدم من النقر المباشر ومن المودال)
  function syncRowStatus(bookId, newState) {
    if (!bookId || !newState) return;
    const display = STATE_DISPLAY[newState] || STATE_DISPLAY.archived;
    document
      .querySelectorAll(`.status-badge-btn[data-book-id="${bookId}"]`)
      .forEach(function (badge) {
        badge.setAttribute("data-current-status", newState);
        // زر بطاقة الجوال = تسمية فِعل + عرض كامل؛ شارة سطح المكتب = اسم الحالة + سهم
        if (badge.closest(".card-status-toggle")) {
          badge.className = "status-badge status-badge-btn badge-status-" + newState + " w-100";
          badge.innerHTML = newState === "archived"
            ? `<i class="bi bi-arrow-counterclockwise"></i> إعادة الفتح`
            : `<i class="bi bi-archive-fill"></i> إنهاء المتابعة`;
        } else {
          badge.className = "status-badge status-badge-btn badge-status-" + newState;
          badge.innerHTML = `<i class="bi ${display.icon}"></i>${display.label}<i class="bi bi-chevron-down status-badge-caret"></i>`;
        }
        const row = badge.closest("tr, .book-card");
        if (row) {
          row.setAttribute("data-status", newState);
          row.setAttribute("data-followup-state", newState);
          ["pending", "due_today", "overdue", "archived"].forEach(function (s) {
            row.classList.remove("book-row-" + s, "book-card-" + s);
          });
          const prefix = row.tagName === "TR" ? "book-row-" : "book-card-";
          row.classList.add(prefix + newState);
        }
      });
  }

  function handleStatusBadgeClick(target) {
    const badge = target.closest(".status-badge-btn");
    if (!badge) return false;
    openStatusPopover(badge);
    return true;
  }

  // مزامنة صف القائمة عندما تُغيَّر الحالة من مودال المعاينة الموحّد
  document.addEventListener("book:status-changed", function (event) {
    const d = event.detail || {};
    syncRowStatus(String(d.bookId || ""), d.followup_state);
  });

  document.addEventListener("click", function (event) {
    if (handleDeleteClick(event.target)) return;
    if (handleStatusBadgeClick(event.target)) return;
    if (!event.target.closest(".status-popover")) {
      closeStatusPopover();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeStatusPopover();
  });
})();
