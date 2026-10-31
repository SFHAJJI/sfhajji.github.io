// The theme toggle: light, dark, or the system's. Stored per visitor in localStorage (a convenience only).
(function () {
  var KEY = "portfolio-theme";
  var root = document.documentElement;
  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function write(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) { /* private window */ } }
  function apply(v) {
    if (v === "light" || v === "dark") root.setAttribute("data-theme", v);
    else root.removeAttribute("data-theme");
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      var current = root.getAttribute("data-theme") || "auto";
      buttons[i].textContent = buttons[i].getAttribute("data-label-" + current) || current;
      buttons[i].setAttribute("aria-label", buttons[i].getAttribute("data-aria") || "Theme");
    }
  }
  apply(read());
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (!b) return;
    var current = root.getAttribute("data-theme") || "auto";
    var next = current === "auto" ? "dark" : current === "dark" ? "light" : "auto";
    write(next === "auto" ? null : next);
    apply(next === "auto" ? null : next);
  });
})();
