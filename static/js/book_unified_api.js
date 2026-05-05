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
    // We treat desktop rows as source of truth; mobile cards mirror the same page data.
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

  function handlePreviewClick(target) {
    const trigger = target.closest(".btn-preview, .btn-preview-mobile");
    if (!trigger) return false;

    const fileUrl = trigger.getAttribute("data-book-attachment");
    const title = trigger.getAttribute("data-book-title") || "معاينة المستند";
    if (!fileUrl) return true;

    const modalEl = document.getElementById("previewModal");
    const bodyEl = document.getElementById("previewModalBody");
    const titleEl = document.getElementById("previewModalLabel");
    if (!modalEl || !bodyEl || !titleEl) return true;

    titleEl.textContent = title;
    bodyEl.innerHTML = "";

    const lower = fileUrl.toLowerCase();
    if (lower.endsWith(".pdf")) {
      bodyEl.innerHTML = `<iframe src="${fileUrl}" title="${title}" style="width:100%;height:75vh;border:0;"></iframe>`;
    } else {
      bodyEl.innerHTML = `<img src="${fileUrl}" alt="${title}" style="max-width:100%;height:auto;display:block;margin:auto;"/>`;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
    return true;
  }

  function updateStatsAfterDelete(bookRow) {
    // ✅ Smart DOM-only updates: decrement counters based on deleted row's attributes
    
    // Decrement total count
    const totalEl = document.getElementById("statTotal");
    const paginationTotalEl = document.getElementById("paginationTotal");
    if (totalEl && totalEl.textContent) {
      const currentTotal = parseInt(totalEl.textContent, 10);
      const newTotal = Math.max(0, currentTotal - 1);
      totalEl.textContent = newTotal;
      if (paginationTotalEl) paginationTotalEl.textContent = newTotal;
    }

    // Determine time_state from row classes
    const hasRowDone = bookRow.classList.contains("book-row-done");
    const hasRowOverdue = bookRow.classList.contains("book-row-overdue");
    const hasRowToday = bookRow.classList.contains("book-row-today");

    // Decrement done count if applicable
    if (hasRowDone) {
      const doneEl = document.getElementById("statDone");
      if (doneEl && doneEl.textContent) {
        doneEl.textContent = Math.max(0, parseInt(doneEl.textContent, 10) - 1);
      }
    }

    // Decrement overdue count if applicable
    if (hasRowOverdue) {
      const overdueEl = document.getElementById("statOverdue");
      if (overdueEl && overdueEl.textContent) {
        overdueEl.textContent = Math.max(0, parseInt(overdueEl.textContent, 10) - 1);
      }
    }

    // Decrement today count if applicable
    if (hasRowToday) {
      const todayEl = document.getElementById("statToday");
      if (todayEl && todayEl.textContent) {
        todayEl.textContent = Math.max(0, parseInt(todayEl.textContent, 10) - 1);
      }
    }

    // Update pagination info
    const paginationFromEl = document.getElementById("paginationFrom");
    const paginationToEl = document.getElementById("paginationTo");
    if (paginationToEl && paginationToEl.textContent) {
      const currentTo = parseInt(paginationToEl.textContent, 10);
      const newTo = Math.max(0, currentTo - 1);
      paginationToEl.textContent = newTo;

      if (paginationFromEl && paginationFromEl.textContent) {
        const currentFrom = parseInt(paginationFromEl.textContent, 10);
        // Keep range valid locally until page fallback logic runs.
        if (newTo === 0) {
          paginationFromEl.textContent = 0;
        } else if (currentFrom > newTo) {
          paginationFromEl.textContent = newTo;
        }
      }
    }
  }

  async function handleDeleteClick(target) {
    const trigger = target.closest(".btn-delete, .btn-delete-mobile");
    if (!trigger) return false;

    const deleteUrl = trigger.getAttribute("data-delete-url");
    const bookRow = trigger.closest("tr, .book-card");
    const bookId = trigger.getAttribute("data-book-id") || (bookRow ? bookRow.getAttribute("data-book-id") : "");
    if (!deleteUrl || !bookRow) return true;

    const bookNumber = trigger.getAttribute("data-book-number") || "";
    const confirmed = window.confirm(`تأكيد حذف الكتاب ${bookNumber}؟ سيتم نقله إلى السلة.`);
    if (!confirmed) return true;

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

    return true;
  }

  async function handleStatusClick(target) {
    const trigger = target.closest(".btn-toggle-status, .btn-toggle-status-mobile");
    if (!trigger) return false;

    const statusUrl = trigger.getAttribute("data-status-url");
    const status = trigger.getAttribute("data-status");
    if (!statusUrl || !status) return true;

    if (trigger.classList.contains("active")) {
      return true;
    }

    trigger.disabled = true;

    try {
      const body = new URLSearchParams();
      body.append("status", status);

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

      // ✅ Smart update: Update button states immediately without reload
      const group = trigger.closest(".btn-group");
      if (group) {
        group.querySelectorAll(".btn-toggle-status, .btn-toggle-status-mobile").forEach(function (btn) {
          btn.classList.remove("active");
          btn.disabled = false;
        });
      }
      trigger.classList.add("active");
      trigger.disabled = false;

      // ✅ Smart update: Update row class for visual feedback only
      // (Status is updated on server, but visual feedback happens immediately)
      const bookRow = trigger.closest("tr, .book-card");
      if (bookRow && status === "done") {
        // If marking as done, store current state before changing classes
        const wasOverdue = bookRow.classList.contains("book-row-overdue");
        const wasToday = bookRow.classList.contains("book-row-today");
        
        // Update the row styling
        bookRow.classList.remove("book-row-overdue", "book-row-today", "book-row-upcoming", "book-row-normal");
        bookRow.classList.add("book-row-done");
        
        // Increment done count
        const doneEl = document.getElementById("statDone");
        if (doneEl && doneEl.textContent) {
          doneEl.textContent = parseInt(doneEl.textContent, 10) + 1;
        }
        
        // Decrement others based on previous state
        if (wasOverdue) {
          const overdueEl = document.getElementById("statOverdue");
          if (overdueEl && overdueEl.textContent) {
            overdueEl.textContent = Math.max(0, parseInt(overdueEl.textContent, 10) - 1);
          }
        }
        if (wasToday) {
          const todayEl = document.getElementById("statToday");
          if (todayEl && todayEl.textContent) {
            todayEl.textContent = Math.max(0, parseInt(todayEl.textContent, 10) - 1);
          }
        }
      }

      showToast(payload.message || "تم تحديث الحالة", "success");
    } catch (error) {
      showToast(error.message || "حدث خطأ أثناء تحديث الحالة", "error");
      trigger.disabled = false;
    }

    return true;
  }

  document.addEventListener("click", function (event) {
    if (handlePreviewClick(event.target)) return;
    if (handleDeleteClick(event.target)) return;
    handleStatusClick(event.target);
  });
})();
