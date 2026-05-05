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

    function parseCount(id) {
      const el = document.getElementById(id);
      if (!el) return 0;
      const value = parseInt(el.textContent || "0", 10);
      return Number.isNaN(value) ? 0 : value;
    }

    function setCount(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = String(Math.max(0, value));
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

    function handlePaginationEdgeAfterBulkDelete() {
      const remainingBooks = document.querySelectorAll("tr.book-row").length;
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

    function removeBooksFromDom(bookIds) {
      if (!bookIds || bookIds.length === 0) return;
      bookIds.forEach(function (id) {
        document
          .querySelectorAll(`tr.book-row[data-book-id="${id}"], .book-card[data-book-id="${id}"]`)
          .forEach(function (el) {
            el.remove();
          });
      });
    }

    function updateCountersAfterBulkDelete(bookIds) {
      const statDelta = {
        done: 0,
        overdue: 0,
        today: 0,
      };

      bookIds.forEach(function (id) {
        const row = document.querySelector(`tr.book-row[data-book-id="${id}"]`);
        if (!row) return;
        if (row.classList.contains("book-row-done")) statDelta.done += 1;
        if (row.classList.contains("book-row-overdue")) statDelta.overdue += 1;
        if (row.classList.contains("book-row-today")) statDelta.today += 1;
      });

      const deletedCount = bookIds.length;
      setCount("statTotal", parseCount("statTotal") - deletedCount);
      setCount("paginationTotal", parseCount("paginationTotal") - deletedCount);
      setCount("statDone", parseCount("statDone") - statDelta.done);
      setCount("statOverdue", parseCount("statOverdue") - statDelta.overdue);
      setCount("statToday", parseCount("statToday") - statDelta.today);

      const newTo = Math.max(0, parseCount("paginationTo") - deletedCount);
      setCount("paginationTo", newTo);
      if (newTo === 0) {
        setCount("paginationFrom", 0);
      } else {
        setCount("paginationFrom", Math.min(parseCount("paginationFrom"), newTo));
      }
    }

    function applyStatusToBookInDom(bookId, status) {
      const row = document.querySelector(`tr.book-row[data-book-id="${bookId}"]`);
      const card = document.querySelector(`.book-card[data-book-id="${bookId}"]`);

      if (row) {
        row.setAttribute("data-status", status);
        const wasDone = row.classList.contains("book-row-done");
        const wasOverdue = row.classList.contains("book-row-overdue");
        const wasToday = row.classList.contains("book-row-today");

        if (status === "done") {
          row.classList.remove("book-row-overdue", "book-row-today", "book-row-upcoming", "book-row-normal");
          row.classList.add("book-row-done");

          if (!wasDone) {
            setCount("statDone", parseCount("statDone") + 1);
          }
          if (wasOverdue) {
            setCount("statOverdue", parseCount("statOverdue") - 1);
          }
          if (wasToday) {
            setCount("statToday", parseCount("statToday") - 1);
          }
        }

        row.querySelectorAll(".btn-toggle-status").forEach(function (btn) {
          btn.classList.toggle("active", btn.getAttribute("data-status") === status);
          btn.disabled = false;
        });
      }

      if (card) {
        if (status === "done") {
          card.classList.remove("book-card-overdue", "book-card-today", "book-card-upcoming", "book-card-normal");
          card.classList.add("book-card-done");
        }
        card.querySelectorAll(".btn-toggle-status-mobile").forEach(function (btn) {
          btn.classList.toggle("active", btn.getAttribute("data-status") === status);
          btn.disabled = false;
        });
      }
    }

    function announceMessage(message) {
      if (liveRegion) liveRegion.textContent = message;
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

      if (selectAll && rows.length > 0) {
        selectAll.checked = checked === rows.length;
        selectAll.indeterminate = checked > 0 && checked < rows.length;
      }
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

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        document.querySelectorAll(".row-checkbox").forEach(function (cb) {
          cb.checked = false;
        });
        if (selectAll) {
          selectAll.checked = false;
          selectAll.indeterminate = false;
        }
        refreshSelection();
      });
    }

    if (bulkDeleteBtn) {
      bulkDeleteBtn.addEventListener("click", async function () {
        const selectedIds = getSelectedBookIds();
        if (selectedIds.length === 0) return;

        const confirmed = window.confirm(`تأكيد حذف ${selectedIds.length} كتاب؟ سيتم نقلها إلى السلة.`);
        if (!confirmed) return;

        const deleteUrl = pageRoot ? pageRoot.getAttribute("data-bulk-delete-url") : "";
        if (!deleteUrl) return;

        bulkDeleteBtn.disabled = true;
        try {
          const response = await fetch(deleteUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCsrfToken(),
              "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ book_ids: selectedIds }),
          });

          const payload = await response.json();
          if (!response.ok || !payload.success) {
            throw new Error(payload.error || "فشل الحذف المتعدد");
          }

          updateCountersAfterBulkDelete(selectedIds);
          removeBooksFromDom(selectedIds);
          refreshSelection();
          announceMessage(payload.message || "تم تنفيذ الحذف المتعدد بنجاح");
          handlePaginationEdgeAfterBulkDelete();
          bulkDeleteBtn.disabled = false;
        } catch (error) {
          announceMessage(error.message || "حدث خطأ أثناء الحذف المتعدد");
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
          announceMessage("يرجى اختيار حالة جديدة قبل التأكيد");
          return;
        }

        const statusUrl = pageRoot ? pageRoot.getAttribute("data-bulk-status-url") : "";
        if (!statusUrl) return;

        confirmBulkUpdateBtn.disabled = true;
        try {
          const response = await fetch(statusUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCsrfToken(),
              "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({ book_ids: selectedIds, status: status }),
          });

          const payload = await response.json();
          if (!response.ok || !payload.success) {
            throw new Error(payload.error || "فشل التحديث المتعدد");
          }

          if (status !== "done") {
            announceMessage(payload.message || "تم تحديث الحالة المتعدد بنجاح");
            if (bulkUpdateModalEl && window.bootstrap && window.bootstrap.Modal) {
              const modal = window.bootstrap.Modal.getOrCreateInstance(bulkUpdateModalEl);
              modal.hide();
            }
            confirmBulkUpdateBtn.disabled = false;
            window.location.reload();
            return;
          }

          selectedIds.forEach(function (id) {
            applyStatusToBookInDom(id, status);
          });
          refreshSelection();
          announceMessage(payload.message || "تم تحديث الحالة المتعدد بنجاح");

          if (bulkUpdateModalEl && window.bootstrap && window.bootstrap.Modal) {
            const modal = window.bootstrap.Modal.getOrCreateInstance(bulkUpdateModalEl);
            modal.hide();
          }

          confirmBulkUpdateBtn.disabled = false;
        } catch (error) {
          announceMessage(error.message || "حدث خطأ أثناء التحديث المتعدد");
          confirmBulkUpdateBtn.disabled = false;
        }
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        const anyChecked = document.querySelectorAll(".row-checkbox:checked").length > 0;
        if (!anyChecked) return;
        document.querySelectorAll(".row-checkbox").forEach(function (cb) {
          cb.checked = false;
        });
        if (selectAll) {
          selectAll.checked = false;
          selectAll.indeterminate = false;
        }
        refreshSelection();
      }
    });

    refreshSelection();
  });
})();
