(function () {
  var DURATION = 3000;

  function dismiss(el) {
    window.setTimeout(function () { el.remove(); }, DURATION);
  }

  document.querySelectorAll("[data-toast]").forEach(dismiss);

  window.showToast = function (message) {
    var region = document.querySelector(".toast-region");
    if (!region) { return; }
    var el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("data-toast", "");
    el.textContent = message;
    region.appendChild(el);
    dismiss(el);
  };
})();
