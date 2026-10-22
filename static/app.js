document.querySelectorAll("[data-autosubmit]").forEach((form) => {
  form.addEventListener("change", () => form.submit());
});

const sheet = document.querySelector("[data-sheet]");
if (sheet) {
  const rows = sheet.querySelectorAll(".row").length;
  const out = {};
  sheet.querySelectorAll("[data-count]").forEach((el) => {
    out[el.dataset.count] = el;
  });

  const update = () => {
    const counts = { Present: 0, Late: 0, Absent: 0 };
    sheet.querySelectorAll("input[type=radio]:checked").forEach((input) => {
      counts[input.value] += 1;
    });
    out.Present.textContent = counts.Present;
    out.Late.textContent = counts.Late;
    out.Absent.textContent = counts.Absent;
    out.None.textContent = rows - counts.Present - counts.Late - counts.Absent;
  };

  sheet.addEventListener("change", update);
  const allPresent = sheet.querySelector("[data-all-present]");
  if (allPresent) {
    allPresent.addEventListener("click", () => {
      sheet.querySelectorAll('input[type=radio][value="Present"]').forEach((input) => {
        input.checked = true;
      });
      update();
    });
  }
  update();
}
