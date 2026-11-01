(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  const meta = document.querySelector('meta[name="token"]');
  const token = params.get("t") || (meta && meta.content) || "";
  const box = document.getElementById("captions");
  let state = null;

  function render() {
    if (!state) return;
    const s = state.subtitle_settings;
    const colors = state.palettes[s.palette] || ["#ffffff", "#000000"];
    const transparent = params.get("bg") === "transparent" || s.palette === "透明";
    document.body.style.background = transparent ? "transparent" : colors[1];
    document.body.style.color = colors[0];
    box.style.fontSize = s.font_size + "px";
    let items = state.captions || [];
    if (s.display_mode === "说完再出") items = items.filter((c) => c.is_final !== false);
    items = items.slice(-Math.max(1, s.retained_sentences) * Math.max(1, (s.reading_languages || []).length));
    box.textContent = "";
    items.forEach((caption) => {
      const item = document.createElement("div");
      item.className = "caption";
      if (s.show_original && caption.original) {
        const o = document.createElement("div");
        o.className = "orig";
        o.textContent = caption.original;
        item.appendChild(o);
      }
      const t = document.createElement("div");
      t.className = "trans";
      t.textContent = ((s.reading_languages || []).length > 1 && caption.target_language
        ? "[" + caption.target_language + "] " : "") + caption.translated;
      item.appendChild(t);
      if (s.show_stats && caption.timing) {
        const st = document.createElement("div");
        st.className = "stats";
        st.textContent = "ASR " + (caption.timing.asr_ms || 0) + " ms · MT " + (caption.timing.mt_ms || 0) + " ms";
        item.appendChild(st);
      }
      box.appendChild(item);
    });
    if (!items.length) {
      const p = document.createElement("div");
      p.className = "caption orig";
      p.textContent = "…";
      box.appendChild(p);
    }
  }

  async function load() {
    const r = await fetch("/api/snapshot", { headers: { "X-Token": token } });
    if (r.ok) { state = await r.json(); render(); }
  }

  load();
  const events = new EventSource("/api/events?t=" + encodeURIComponent(token));
  events.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "state") { state = e.state; render(); }
    else if (e.type === "resync") load();
  };
})();
