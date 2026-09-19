(function () {
  var MIN_OPTIONS = 2;
  var MAX_OPTIONS = 5;

  var list = document.querySelector("[data-option-list]");
  if (!list) { return; }

  function allRows() {
    return Array.prototype.slice.call(list.querySelectorAll("[data-option-row]"));
  }

  function visibleRows() {
    return allRows().filter(function (row) { return !row.hidden; });
  }

  function inputOf(row) {
    return row.querySelector("input");
  }

  var addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "btn btn-secondary option-add";
  addButton.textContent = "Seçenek ekle";
  list.insertAdjacentElement("afterend", addButton);

  function update() {
    var visible = visibleRows();
    visible.forEach(function (row, i) {
      var input = inputOf(row);
      input.placeholder = "Seçenek " + (i + 1);
      input.setAttribute("aria-label", "Seçenek " + (i + 1));
      row.querySelector("[data-remove-option]").hidden = visible.length <= MIN_OPTIONS;
    });
    addButton.disabled = visible.length >= MAX_OPTIONS;
  }

  allRows().forEach(function (row, i) {
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-secondary option-remove";
    remove.setAttribute("data-remove-option", "");
    remove.textContent = "Kaldır";
    remove.addEventListener("click", function () {
      inputOf(row).value = "";
      row.hidden = true;
      list.appendChild(row);
      update();
      addButton.focus();
    });
    row.appendChild(remove);

    if (i >= MIN_OPTIONS && inputOf(row).value.trim() === "") {
      row.hidden = true;
    }
  });

  addButton.addEventListener("click", function () {
    var next = allRows().filter(function (row) { return row.hidden; })[0];
    if (!next) { return; }
    next.hidden = false;
    update();
    inputOf(next).focus();
  });

  update();
})();
