(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const selectAll = document.getElementById("selectAllBooks");
    if (!selectAll) return;

    selectAll.addEventListener("change", function () {
      document.querySelectorAll(".row-checkbox").forEach(function (cb) {
        cb.checked = selectAll.checked;
      });
    });
  });
})();
