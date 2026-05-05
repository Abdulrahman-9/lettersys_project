(function () {
  class BookUnifiedApp {
    constructor(options) {
      this.options = options || {};
      this.state = {
        currentTab: this.options.currentTab || "all",
        filters: this.options.initialFilters || {},
      };
    }

    loadData() {
      // Server-rendered mode in Phase 1: keep this no-op to avoid API dependency.
      return Promise.resolve();
    }

    setQueryParam(key, value) {
      const url = new URL(window.location.href);
      if (value === null || value === undefined || value === "") {
        url.searchParams.delete(key);
      } else {
        url.searchParams.set(key, String(value));
      }
      url.searchParams.delete("page");
      window.location.href = url.toString();
    }

    setManyQueryParams(params) {
      const url = new URL(window.location.href);
      Object.keys(params).forEach(function (key) {
        const value = params[key];
        if (value === null || value === undefined || value === "") {
          url.searchParams.delete(key);
        } else {
          url.searchParams.set(key, String(value));
        }
      });
      url.searchParams.delete("page");
      window.location.href = url.toString();
    }

    resetAllFilters() {
      this.state.filters = {};
      const url = new URL(window.location.href);
      ["q", "date_from", "date_to", "entity_id", "status", "due_status", "has_attachment", "sort", "page"].forEach(
        function (key) {
          url.searchParams.delete(key);
        }
      );
      window.location.href = url.toString();
    }
  }

  window.BookUnifiedApp = BookUnifiedApp;
})();
