"use strict";

(function () {
  var key = "plankton-time.appearance";
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  var picker;

  function stored() {
    try { return localStorage.getItem(key); }
    catch (error) { return null; }
  }
  function choice(value) {
    return value === "light" || value === "dark" ? value : "system";
  }
  var preference = choice(stored());

  function apply() {
    var active = preference === "system" ? (media.matches ? "dark" : "light") : preference;
    document.documentElement.setAttribute("data-pl-brand-theme", active);
    if (picker) picker.value = preference;
  }
  apply();
  if (media.addEventListener) media.addEventListener("change", apply);
  else media.addListener(apply);
  window.addEventListener("storage", function (event) {
    if (event.key === key || event.key === null) {
      preference = choice(stored());
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    picker = document.querySelector("[data-brand-theme-picker]");
    if (!picker) return;
    picker.parentElement.hidden = false;
    picker.value = preference;
    picker.addEventListener("change", function () {
      preference = choice(picker.value);
      try { localStorage.setItem(key, preference); }
      catch (error) { /* The selected mode still applies to this page. */ }
      apply();
    });
  });
})();
