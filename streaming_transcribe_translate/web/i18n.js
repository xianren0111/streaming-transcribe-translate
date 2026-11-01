/* Interface text translation. Chinese source strings are looked up in the shared
   TRANSLATIONS table (served by /api/i18n) using the same whole-string, then
   longest-substring approach as ui_localization.Translator. */
(function () {
  "use strict";
  const meta = document.querySelector('meta[name="app-token"]');
  let token = meta ? meta.content : "";
  if (!token || token === "__TOKEN__") {
    token = new URLSearchParams(location.search).get("t") || sessionStorage.getItem("token") || "";
  }
  if (token) sessionStorage.setItem("token", token);

  const I18N = {
    token,
    language: "zh",
    table: {},
    pattern: null,
    missing: new Set(),
    async load() {
      const response = await fetch("/api/i18n", { headers: { "X-Token": token } });
      this.table = await response.json();
      const keys = Object.keys(this.table).sort((a, b) => b.length - a.length);
      const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      this.pattern = keys.length ? new RegExp(keys.map(escape).join("|"), "g") : null;
    },
    t(text) {
      if (this.language === "zh" || !text) return text;
      const entry = this.table[text];
      if (entry) return entry[this.language] || text;
      if (!this.pattern) return text;
      const result = text.replace(this.pattern, (match) => this.table[match][this.language] || match);
      if (/[\u4e00-\u9fff]/.test(text.replace(this.pattern, "")) && !this.missing.has(text)) {
        this.missing.add(text);
        console.warn("Missing translation:", text);
      }
      return result;
    },
  };
  window.I18N = I18N;
  window.t = (text) => I18N.t(text);
})();
