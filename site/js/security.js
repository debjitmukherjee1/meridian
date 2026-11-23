/* security.js -- loaded before any other script on every page served from
   debjitmukherjee1.github.io (added 23-Nov-2026 after an authorised red-team
   test found DOM XSS in two same-origin tools).

   1. Clickjacking guard. GitHub Pages cannot send X-Frame-Options or a
      frame-ancestors header, so a framed copy of the page redirects the top
      window or hides itself.
   2. Trusted Types default policy. The page's Content-Security-Policy says
      require-trusted-types-for 'script', so the browser refuses raw strings in
      innerHTML/outerHTML/insertAdjacentHTML/document.write and in script URLs.
      This policy is the only way through: every HTML string is run through
      DOMPurify (scripts, event handlers and javascript: URLs removed), script
      URLs must be this site or Google Tag Manager, and string-to-code
      (eval-style) is refused. A future escaping mistake therefore cannot run
      script, even if it slips past review.
*/
(function () {
  "use strict";
  if (window.top !== window.self) {
    try { window.top.location.replace(window.self.location.href); }
    catch (e) { document.documentElement.style.display = "none"; }
  }
  var tt = window.trustedTypes, P = window.DOMPurify;
  if (!tt || !tt.createPolicy) return;
  if (P && P.addHook) {
    P.addHook("afterSanitizeAttributes", function (n) {
      if (n.getAttribute && n.getAttribute("target")) n.setAttribute("rel", "noopener noreferrer");
    });
  }
  var SCRIPT_ORIGINS = [location.origin, "https://www.googletagmanager.com"];
  try {
    tt.createPolicy("default", {
      createHTML: function (s) {
        if (!P) throw new TypeError("HTML sanitizer unavailable");
        s = String(s);
        // Table fragments ("<tr>...", "<td>...") vanish if sanitised on their
        // own, because the HTML parser drops rows outside a table. Sanitise
        // them inside a table and hand back just the inner part.
        var m = /^\s*<(tr|td|th|thead|tbody|tfoot|caption|colgroup|col)\b/i.exec(s);
        if (!m) return P.sanitize(s, { ADD_ATTR: ["target"] });
        var t = m[1].toLowerCase();
        var w = t === "tr" ? ["<table><tbody>", "</tbody></table>", "tbody"]
              : (t === "td" || t === "th") ? ["<table><tbody><tr>", "</tr></tbody></table>", "tr"]
              : ["<table>", "</table>", "table"];
        var body = P.sanitize(w[0] + s + w[1], { ADD_ATTR: ["target"], RETURN_DOM: true });
        var holder = body && body.querySelector(w[2]);
        return holder ? holder.innerHTML : "";
      },
      createScriptURL: function (u) {
        var x = new URL(String(u), location.href);
        if (SCRIPT_ORIGINS.indexOf(x.origin) !== -1) return x.href;
        throw new TypeError("Blocked script URL from " + x.origin);
      },
      createScript: function () { throw new TypeError("Blocked string-to-script"); }
    });
  } catch (e) { /* default policy already defined */ }
})();
