(function () {
  var button = document.querySelector("[data-result-card]");
  if (!button) { return; }

  var WIDTH = 1080;
  var PAD = 72;
  var FILE_NAME = "kararsizlik-karti.png";

  function toast(message) {
    if (window.showToast) { window.showToast(message); }
  }

  // Renkler ve yazı tipleri CSS token'larından okunur; JS içinde ham renk yok.
  function tokens() {
    var css = getComputedStyle(document.documentElement);
    var read = function (name) { return css.getPropertyValue(name).trim(); };
    return {
      paper: read("--paper"), surface: read("--surface"), ink: read("--ink"), muted: read("--muted"), violet: read("--violet"),
      options: [read("--opt-0"), read("--opt-1"), read("--opt-2"), read("--opt-3"), read("--opt-4")],
      display: read("--font-display"), body: read("--font-body"), mono: read("--font-mono")
    };
  }

  function wrap(ctx, text, maxWidth) {
    var words = text.split(/\s+/);
    var lines = [];
    var line = "";
    words.forEach(function (word) {
      var test = line ? line + " " + word : word;
      if (ctx.measureText(test).width > maxWidth && line) {
        lines.push(line);
        line = word;
      } else {
        line = test;
      }
    });
    if (line) { lines.push(line); }
    return lines;
  }

  function roundRect(ctx, x, y, w, h, r) {
    var radius = Math.min(r, h / 2, w / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function fit(ctx, text, maxWidth) {
    if (ctx.measureText(text).width <= maxWidth) { return text; }
    var cut = text;
    while (cut.length > 1 && ctx.measureText(cut + "…").width > maxWidth) { cut = cut.slice(0, -1); }
    return cut + "…";
  }

  function draw(data, question) {
    var t = tokens();
    var measure = document.createElement("canvas").getContext("2d");
    measure.font = "800 60px " + t.display;
    var lines = wrap(measure, question, WIDTH - PAD * 2).slice(0, 4);

    var questionHeight = lines.length * 74;
    var optionsTop = PAD + 70 + 40 + questionHeight + 84;
    var rowHeight = 118;
    var height = optionsTop + data.options.length * rowHeight + 40 + 70 + 80 + PAD;

    var canvas = document.createElement("canvas");
    canvas.width = WIDTH;
    canvas.height = height;
    var ctx = canvas.getContext("2d");
    ctx.textBaseline = "top";

    ctx.fillStyle = t.paper;
    ctx.fillRect(0, 0, WIDTH, height);

    ctx.fillStyle = t.violet;
    roundRect(ctx, PAD, PAD, 56, 56, 14);
    ctx.fill();
    ctx.fillStyle = t.surface;
    roundRect(ctx, PAD + 12, PAD + 13, 32, 8, 4); ctx.fill();
    ctx.fillStyle = t.options[1];
    roundRect(ctx, PAD + 12, PAD + 24, 22, 8, 4); ctx.fill();
    ctx.fillStyle = t.options[2];
    roundRect(ctx, PAD + 12, PAD + 35, 14, 8, 4); ctx.fill();
    ctx.fillStyle = t.ink;
    ctx.font = "800 40px " + t.display;
    ctx.fillText("Kararsızım", PAD + 74, PAD + 6);

    ctx.font = "800 60px " + t.display;
    ctx.fillStyle = t.ink;
    lines.forEach(function (line, i) { ctx.fillText(line, PAD, PAD + 110 + i * 74); });

    ctx.font = "500 30px " + t.mono;
    ctx.fillStyle = t.muted;
    var totalText = data.total + " kişi oy verdi";
    ctx.fillText(totalText, PAD, PAD + 110 + questionHeight + 10);

    data.options.forEach(function (option, i) {
      var y = optionsTop + i * rowHeight;
      var mine = option.id === data.voted_option_id;
      ctx.font = "600 38px " + t.body;
      ctx.fillStyle = t.ink;
      var label = (mine ? "✓ " : "") + option.text;
      ctx.fillText(fit(ctx, label, WIDTH - PAD * 2 - 170), PAD, y);
      ctx.font = "500 38px " + t.mono;
      ctx.textAlign = "right";
      ctx.fillText("%" + option.percent, WIDTH - PAD, y);
      ctx.textAlign = "left";

      var barY = y + 58;
      var barW = WIDTH - PAD * 2;
      ctx.globalAlpha = 0.08;
      ctx.fillStyle = t.ink;
      roundRect(ctx, PAD, barY, barW, 30, 15); ctx.fill();
      ctx.globalAlpha = 1;
      if (option.percent > 0) {
        ctx.fillStyle = t.options[i % t.options.length];
        roundRect(ctx, PAD, barY, Math.max(30, barW * option.percent / 100), 30, 15); ctx.fill();
      }
    });

    var badgeY = optionsTop + data.options.length * rowHeight + 20;
    ctx.font = "600 34px " + t.body;
    var badgeW = ctx.measureText(data.badge).width + 56;
    ctx.globalAlpha = 0.12;
    ctx.fillStyle = t.violet;
    roundRect(ctx, PAD, badgeY, badgeW, 64, 32); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = t.ink;
    ctx.fillText(data.badge, PAD + 28, badgeY + 14);

    ctx.font = "500 30px " + t.mono;
    ctx.fillStyle = t.muted;
    ctx.fillText(location.host + " · Sen de oy ver", PAD, height - PAD - 30);
    return canvas;
  }

  function deliver(canvas) {
    canvas.toBlob(function (blob) {
      if (!blob) { toast("Kart oluşturulamadı."); return; }
      var file = new File([blob], FILE_NAME, { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: "Kararsızlık kartı" }).catch(function (error) {
          if (error && error.name !== "AbortError") { download(blob); }
        });
      } else {
        download(blob);
      }
    }, "image/png");
  }

  function download(blob) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = FILE_NAME;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast("Kart indirildi.");
  }

  if (button.hasAttribute("data-eligible")) { button.hidden = false; }

  button.addEventListener("click", function () {
    var question = document.querySelector(".poll-question").textContent.trim();
    var resultsUrl = location.pathname.replace(/\/?$/, "/") + "sonuc/";
    button.disabled = true;
    fetch(resultsUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.options.length || !("percent" in data.options[0]) || !data.total) {
          toast("Sonuçlar oy verince açılır.");
          return null;
        }
        var t = tokens();
        var fonts = ["800 60px " + t.display, "600 38px " + t.body, "500 30px " + t.mono];
        return Promise.all(fonts.map(function (font) { return document.fonts.load(font); }))
          .catch(function () {})
          .then(function () { return document.fonts.ready; })
          .then(function () { deliver(draw(data, question)); });
      })
      .catch(function () { toast("Kart oluşturulamadı. Tekrar dene."); })
      .then(function () { button.disabled = false; });
  });
})();
