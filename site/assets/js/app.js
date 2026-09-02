(() => {
  "use strict";

  const number = new Intl.NumberFormat("en-US");

  function formatBytes(bytes) {
    return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
  }

  function setText(selector, value) {
    const node = document.querySelector(selector);
    if (node) node.textContent = value;
  }

  function renderClasses(classes) {
    const list = document.getElementById("class-list");
    if (!list || !classes) return;
    const entries = Object.entries(classes);
    const maximum = Math.max(...entries.map(([, count]) => count));
    list.replaceChildren(...entries.map(([name, count]) => {
      const row = document.createElement("div");
      row.className = "class-row";
      const heading = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = name;
      const value = document.createElement("strong");
      value.textContent = number.format(count);
      heading.append(label, value);
      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("i");
      fill.style.width = `${(count / maximum * 100).toFixed(2)}%`;
      bar.append(fill);
      row.append(heading, bar);
      return row;
    }));
  }

  async function loadStats() {
    try {
      const response = await fetch("./data/stats.json", { cache: "no-cache" });
      if (!response.ok) throw new Error(`stats request failed: ${response.status}`);
      const stats = await response.json();
      setText('[data-stat="samples"]', number.format(stats.sample_count));
      setText('[data-stat="shards"]', number.format(stats.shard_count));
      setText('[data-stat="members"]', number.format(stats.tar_member_count));
      setText('[data-stat="size"]', formatBytes(stats.payload_bytes));
      renderClasses(stats.classes);
    } catch (error) {
      console.warn("Using embedded dataset statistics.", error);
    }
  }

  function enableCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach((button) => {
      button.addEventListener("click", async () => {
        const source = document.getElementById(button.dataset.copy);
        if (!source) return;
        try {
          await navigator.clipboard.writeText(source.textContent);
          const original = button.textContent;
          button.textContent = "Copied";
          setTimeout(() => { button.textContent = original; }, 1400);
        } catch (error) {
          console.warn("Clipboard is unavailable.", error);
        }
      });
    });
  }

  loadStats();
  enableCopyButtons();
})();
