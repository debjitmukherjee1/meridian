/* suite.js — shared behaviour for the tool suite's bottom tab dock.
   On narrow screens the dock scrolls sideways; keep the active tab in view. */
(function () {
  var dock = document.querySelector(".tabs");
  if (!dock) return;
  function reveal(tab) {
    if (!tab || dock.scrollWidth <= dock.clientWidth + 1) return;
    var left = tab.offsetLeft - (dock.clientWidth - tab.offsetWidth) / 2;
    dock.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
  }
  dock.addEventListener("click", function (e) {
    var tab = e.target.closest(".tab");
    if (tab) reveal(tab);
  });
  window.addEventListener("load", function () { reveal(dock.querySelector(".tab.active")); });
})();
