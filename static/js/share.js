(function () {
  var button = document.querySelector("[data-share]");
  if (!button) { return; }

  function toast(message) {
    if (window.showToast) { window.showToast(message); }
  }

  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var done = false;
    try { done = document.execCommand("copy"); } catch (error) { done = false; }
    area.remove();
    return done;
  }

  function copyLink(url) {
    var finish = function (ok) {
      toast(ok ? "Bağlantı kopyalandı." : "Kopyalanamadı. Adresi elle kopyala: " + url);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(url).then(function () { finish(true); }, function () { finish(legacyCopy(url)); });
    } else {
      finish(legacyCopy(url));
    }
  }

  button.hidden = false;
  button.addEventListener("click", function () {
    var url = button.getAttribute("data-share-url");
    var title = button.getAttribute("data-share-title");
    if (navigator.share) {
      navigator.share({ title: title, text: title + " Sen de oy ver.", url: url }).catch(function (error) {
        if (error && error.name !== "AbortError") { copyLink(url); }
      });
    } else {
      copyLink(url);
    }
  });
})();
