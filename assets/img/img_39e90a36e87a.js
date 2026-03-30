(function() {
  const n = document.currentScript;
  n != null && n.src ? import(new URL("kaching-bundles.js", n.src).href) : import("./kaching-bundles.js");
})();
