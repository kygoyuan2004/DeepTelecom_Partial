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

  function renderClasses(classes, total) {
    if (!classes || !total) return;
    Object.entries(classes).forEach(([classId, count]) => {
      document.querySelectorAll(`[data-class-count="${classId}"]`).forEach((node) => {
        node.textContent = number.format(count);
      });
      document.querySelectorAll(`[data-class-share="${classId}"]`).forEach((node) => {
        node.textContent = `${(count / total * 100).toFixed(1)}%`;
      });
      document.querySelectorAll(`[data-class-width="${classId}"]`).forEach((node) => {
        node.style.width = `${(count / total * 100).toFixed(4)}%`;
      });
    });
  }

  async function loadStats() {
    try {
      const script = document.querySelector('script[src$="assets/js/app.js"]');
      const statsUrl = script ? new URL("../../data/stats.json", script.src) : "./data/stats.json";
      const response = await fetch(statsUrl, { cache: "no-cache" });
      if (!response.ok) throw new Error(`stats request failed: ${response.status}`);
      const stats = await response.json();
      setText('[data-stat="samples"]', number.format(stats.sample_count));
      setText('[data-stat="shards"]', number.format(stats.shard_count));
      setText('[data-stat="members"]', number.format(stats.tar_member_count));
      setText('[data-stat="size"]', formatBytes(stats.payload_bytes));
      renderClasses(stats.classes, stats.sample_count);
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
          button.textContent = document.documentElement.lang.startsWith("zh") ? "已复制" : "Copied";
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
