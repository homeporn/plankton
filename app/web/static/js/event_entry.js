"use strict";
(function () {
  const work = document.querySelector(".event-form [data-work-item]");
  if (!work) return;
  const context = work.form.querySelector("[data-work-context]");
  function showLocation() {
    const option = work.selectedOptions[0];
    context.textContent = option && option.value ? option.dataset.context :
      "Выберите работу, чтобы увидеть её расположение и единицу измерения.";
  }
  work.addEventListener("change", showLocation);
  showLocation();
}());
