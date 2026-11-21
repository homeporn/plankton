"use strict";

// Give overflowing data regions a keyboard stop, including after a panel opens,
// a viewport changes or a table changes size. Preserve explicit template labels.
document.querySelectorAll("main .table-scroll").forEach(function (region) {
  if (region.hasAttribute("tabindex")) return;
  var table = region.querySelector("table");
  if (!table) return;
  var ownRole = !region.hasAttribute("role");
  var ownLabel = !region.hasAttribute("aria-label") && !region.hasAttribute("aria-labelledby");

  function update() {
    var overflow = region.clientWidth > 0 &&
      (region.scrollWidth > region.clientWidth || region.scrollHeight > region.clientHeight);
    if (overflow) {
      region.tabIndex = 0;
      if (ownRole) region.setAttribute("role", "region");
      if (ownLabel) {
        var section = region.closest("section, details, article") || region.closest("main");
        var heading = table.caption || section.querySelector("h2, summary, h1");
        region.setAttribute("aria-label", heading ? "Таблица · " + heading.textContent.trim() : "Таблица с прокруткой");
      }
    } else {
      region.removeAttribute("tabindex");
      if (ownRole) region.removeAttribute("role");
      if (ownLabel) region.removeAttribute("aria-label");
    }
  }

  update();
  if ("ResizeObserver" in window) {
    var observer = new ResizeObserver(update);
    observer.observe(region);
    observer.observe(table);
  } else {
    window.addEventListener("resize", update);
    document.addEventListener("toggle", update, true);
  }
});
