(function () {
  var form = document.querySelector("[data-vote-form]");
  if (!form) { return; }

  var tokenInput = form.querySelector("[name=csrfmiddlewaretoken]");
  var busy = false;

  function toast(message) {
    if (window.showToast) { window.showToast(message); }
  }

  function renderBar(options) {
    var bar = document.querySelector(".decision-bar");
    if (!bar) { return; }
    bar.textContent = "";
    var label = [];
    options.forEach(function (option, index) {
      label.push(option.text + " %" + option.percent);
      if (!option.percent) { return; }
      var seg = document.createElement("span");
      seg.className = "bar-seg opt-" + index;
      seg.style.width = "0%";
      bar.appendChild(seg);
      // Bir kare bekleyip genişliği ayarlamak geçişi (transition) tetikler.
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () { seg.style.width = option.percent + "%"; });
      });
    });
    bar.classList.remove("decision-bar-neutral");
    bar.setAttribute("aria-label", "Oy dağılımı: " + label.join(", "));
  }

  function render(data) {
    var badge = document.querySelector(".badge");
    if (badge) {
      badge.textContent = data.badge;
      badge.classList.toggle("badge-neutral", !(data.options[0] && "percent" in data.options[0]));
    }
    var total = document.querySelector("[data-total]");
    if (total) {
      total.textContent = data.total ? data.total + " kişi oy verdi" : "Henüz oy yok";
    }

    var hasResults = data.options.length > 0 && "percent" in data.options[0];
    var canVote = data.is_open && data.voted_option_id === null;

    data.options.forEach(function (option) {
      var button = form.querySelector('.option-row[value="' + option.id + '"]');
      if (!button) { return; }
      var isMine = option.id === data.voted_option_id;
      button.classList.toggle("option-row-voted", isMine);
      button.querySelector(".option-check").hidden = !isMine;
      button.disabled = !canVote;
      if (hasResults) {
        button.querySelector(".option-fill").style.width = option.percent + "%";
        button.querySelector(".option-percent").textContent = "%" + option.percent;
      }
    });

    if (hasResults) { renderBar(data.options); }
    if (!canVote) { form.removeAttribute("data-vote-form"); }
  }

  form.addEventListener("submit", function (event) {
    var button = event.submitter;
    if (!button || !button.value || button.disabled) { return; }
    event.preventDefault();
    if (busy) { return; }
    busy = true;
    form.setAttribute("aria-busy", "true");

    var body = new FormData();
    body.append("option_id", button.value);

    fetch(form.action, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": tokenInput ? tokenInput.value : "",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json"
      }
    })
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (result.data.options) { render(result.data); }
        toast(result.ok ? "Oyun kaydedildi." : (result.data.error || "Bir sorun oluştu. Tekrar dene."));
      })
      .catch(function () {
        toast("Bağlantı sorunu. Tekrar dene.");
      })
      .then(function () {
        busy = false;
        form.removeAttribute("aria-busy");
      });
  });
})();
