(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const tabs = document.querySelectorAll(".tab-btn");
    const app = window.bookUnifiedApp;
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        tabs.forEach(function (t) {
          t.classList.remove("active");
          t.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");

        const tabName = btn.dataset.tab || "all";
        if (app && typeof app.setManyQueryParams === "function") {
          app.setManyQueryParams({ tab: tabName });
        }
      });
    });

    const pills = document.querySelectorAll(".pill-filter");
    pills.forEach(function (pill) {
      pill.addEventListener("click", function () {
        const filter = pill.dataset.filter || "all";
        const dueMap = { overdue: "overdue", today: "today", upcoming: "upcoming" };
        if (app && typeof app.setManyQueryParams === "function") {
          if (filter === "all") {
            app.setManyQueryParams({ due_status: "", status: "", tab: "all" });
          } else if (filter === "done") {
            app.setManyQueryParams({ due_status: "", status: "done", tab: "done" });
          } else {
            app.setManyQueryParams({ due_status: dueMap[filter] || "", status: "", tab: filter });
          }
        }
      });
    });

    /* =============================================
     * Sub-menu dropdowns for وارد / صادر tabs
     * ============================================= */
    document.querySelectorAll(".tab-sub-item").forEach(function (item) {
      item.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();

        var wrapper = item.closest(".tab-dropdown-wrapper");
        var parentBtn = wrapper ? wrapper.querySelector(".tab-btn") : null;
        if (!parentBtn) return;

        // Mark active sub-item within this wrapper
        wrapper.querySelectorAll(".tab-sub-item").forEach(function (s) {
          s.classList.remove("active");
        });
        item.classList.add("active");

        // Update parent tab to use the sub-kind value
        var subKind = item.dataset.subKind || parentBtn.dataset.tab;
        parentBtn.dataset.tab = subKind;

        // Close dropdown
        wrapper.classList.remove("open");

        // Trigger parent tab click (activates both JS handlers)
        parentBtn.click();
      });
    });

    // Toggle dropdown on touch devices (click the chevron area)
    document.querySelectorAll(".tab-dropdown-wrapper .tab-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var wrapper = btn.closest(".tab-dropdown-wrapper");
        // Toggle only if not triggered by sub-item
        if (wrapper) wrapper.classList.toggle("open");
      });
    });

    // Close open dropdowns when clicking outside
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".tab-dropdown-wrapper")) {
        document.querySelectorAll(".tab-dropdown-wrapper.open").forEach(function (w) {
          w.classList.remove("open");
        });
      }
    });

    // Restore active sub-item from URL on page load
    var currentTab = new URLSearchParams(window.location.search).get("tab") || "all";
    document.querySelectorAll(".tab-sub-item").forEach(function (item) {
      var wrapper = item.closest(".tab-dropdown-wrapper");
      item.classList.remove("active");
      if (item.dataset.subKind === currentTab) {
        item.classList.add("active");
        // Also set parent tab data-tab to match
        var parentBtn = wrapper ? wrapper.querySelector(".tab-btn") : null;
        if (parentBtn) parentBtn.dataset.tab = currentTab;
      }
    });
  });
})();
