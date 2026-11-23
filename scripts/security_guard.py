"""security_guard.py -- fails CI if any page loses its protections.

Every .html page published from this repo must:
  * carry a Content-Security-Policy meta tag with require-trusted-types-for 'script',
    trusted-types limited to default/dompurify, object-src 'none', base-uri 'self',
    and no 'unsafe-inline' / 'unsafe-eval' in script-src;
  * list the sha256 hash of every inline <script> it runs;
  * load js/vendor/purify.min.js and js/security.js before any other script.
Added 23-Nov-2026 after an authorised red-team test (see commit history).
"""
import base64, hashlib, pathlib, re, sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
EXEMPT = {"404.html"}  # error pages carry the CSP but run no script
bad = []
for page in sorted(root.rglob("*.html")):
    if any(p in page.parts for p in ("node_modules", ".git")) or page.name.startswith("google"):
        continue
    s = page.read_text(errors="ignore")
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', s)
    if not m:
        bad.append(f"{page}: no Content-Security-Policy meta tag"); continue
    csp = m.group(1)
    d = {k.split(" ", 1)[0]: k for k in [x.strip() for x in csp.split(";")] if k}
    if "require-trusted-types-for 'script'" not in csp: bad.append(f"{page}: Trusted Types not enforced")
    if not re.search(r"trusted-types default( dompurify)?($|;)", csp): bad.append(f"{page}: trusted-types allowlist missing or too wide")
    if "object-src 'none'" not in csp: bad.append(f"{page}: object-src not 'none'")
    if "base-uri 'self'" not in csp: bad.append(f"{page}: base-uri not 'self'")
    ss = d.get("script-src", "")
    if not ss: bad.append(f"{page}: no script-src")
    if "'unsafe-inline'" in ss or "'unsafe-eval'" in ss: bad.append(f"{page}: script-src allows unsafe-inline/unsafe-eval")
    for attrs, body in re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", s, re.S):
        if "ld+json" in attrs or not body.strip(): continue
        h = "sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        if h not in ss: bad.append(f"{page}: inline script {h} not in script-src")
    if re.search(r"\son[a-z]+\s*=", re.sub(r"<script.*?</script>", "", s, flags=re.S)):
        bad.append(f"{page}: inline event handler attribute")
    if page.name in EXEMPT: continue
    srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', s)
    if len(srcs) < 2 or not srcs[0].split("?")[0].endswith("purify.min.js") or not srcs[1].split("?")[0].endswith("security.js"):
        bad.append(f"{page}: purify.min.js + security.js must be the first two scripts (found {srcs[:2]})")
if bad:
    print("SECURITY GUARD FAILED:"); print("\n".join("  - " + b for b in bad)); sys.exit(1)
print("security guard: all pages protected")
