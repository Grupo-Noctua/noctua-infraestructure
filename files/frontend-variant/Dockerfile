ARG FRONTEND_BASE=noctua-frontend:base
FROM ${FRONTEND_BASE}
ARG FRONTEND_VARIANT=A
RUN set -eu; \
    case "$FRONTEND_VARIANT" in A) color='#1d4ed8' ;; B) color='#c2410c' ;; *) exit 1 ;; esac; \
    html=/usr/share/nginx/html/index.html; \
    grep -q '</body>' "$html"; \
    if grep -q 'noctua-frontend-variant' "$html"; then exit 1; fi; \
    sed -i "s|</body>|<aside id=\"noctua-frontend-variant\" aria-label=\"Frontend ${FRONTEND_VARIANT} do load balancer\" style=\"position:fixed;bottom:16px;right:16px;z-index:2147483647;padding:12px 18px;border-radius:12px;background:${color};color:white;font:700 14px/1.5 system-ui,sans-serif;box-shadow:0 4px 20px #0003;pointer-events:none\">FRONTEND ${FRONTEND_VARIANT}<br><span style=\"font-size:11px;font-weight:400\">Noctua / Load balancer</span></aside></body>|" "$html"
LABEL io.noctua.frontend.variant=${FRONTEND_VARIANT}
