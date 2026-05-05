(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const input = document.getElementById("liveSearchInput");
    const clear = document.getElementById("clearSearchBtn");
    const app = window.bookUnifiedApp;
    const filterToggleBtn = document.getElementById("filterToggleBtn");
    const advancedFilters = document.getElementById("advancedFilters");
    const resetFiltersBtn = document.getElementById("resetFiltersBtn");
    const filtersForm = document.getElementById("advancedFiltersForm");
    const liveRegion = document.getElementById("bookUnifiedLiveRegion");

    if (!input || !clear) return;

    let timer = null;

    input.addEventListener("input", function () {
      clear.style.display = input.value ? "inline-flex" : "none";

      clearTimeout(timer);
      timer = setTimeout(function () {
        if (app && typeof app.setQueryParam === "function") {
          if (liveRegion) liveRegion.textContent = "جارٍ تطبيق البحث";
          app.setQueryParam("q", input.value.trim());
        }
      }, 300);
    });

    clear.addEventListener("click", function () {
      input.value = "";
      clear.style.display = "none";
      input.focus();
      if (app && typeof app.setQueryParam === "function") {
        app.setQueryParam("q", "");
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const tag = (event.target && event.target.tagName) || "";
        if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
          event.preventDefault();
          input.focus();
          input.select();
        }
      }
    });

    if (filterToggleBtn && advancedFilters) {
      filterToggleBtn.addEventListener("click", function () {
        const hidden = advancedFilters.style.display === "none";
        advancedFilters.style.display = hidden ? "block" : "none";
        filterToggleBtn.setAttribute("aria-expanded", hidden ? "true" : "false");
      });
    }

    if (resetFiltersBtn) {
      resetFiltersBtn.addEventListener("click", function () {
        if (app && typeof app.resetAllFilters === "function") {
          app.resetAllFilters();
        }
      });
    }

    if (filtersForm) {
      filtersForm.addEventListener("submit", function (event) {
        event.preventDefault();
        const formData = new FormData(filtersForm);
        const params = {};
        formData.forEach(function (value, key) {
          params[key] = value;
        });
        if (app && typeof app.setManyQueryParams === "function") {
          app.setManyQueryParams(params);
        }
      });
    }
  });
})();
