// Shared by the local HTTP proxy and the Next.js /sandbox route.
function validateHostOrigins(hostOrigins: readonly string[]) {
  if (!hostOrigins.length) throw new Error("Missing host origin");
  for (const origin of hostOrigins) {
    const parsed = new URL(origin);
    if (parsed.origin !== origin || !["http:", "https:"].includes(parsed.protocol)) throw new Error("Invalid host origin");
  }
}

export function sandboxHeaders(hostOrigins: readonly string[]): Record<string, string> {
  validateHostOrigins(hostOrigins);
  return {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Security-Policy": [
      "default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'",
      "connect-src 'none'", "img-src data:", "frame-src 'self'", "base-uri 'none'",
      "object-src 'none'", "form-action 'none'", `frame-ancestors ${hostOrigins.join(" ")}`,
    ].join("; "),
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-write=()",
    "Referrer-Policy": "no-referrer",
  };
}

export function sandboxDocument(hostOrigins: readonly string[]) {
  validateHostOrigins(hostOrigins);
  const allowed = JSON.stringify(hostOrigins).replaceAll("<", "\\u003c");
  return `<!doctype html><html><head><meta charset="utf-8"><title>MCP Apps sandbox</title>
<style>html,body{margin:0;height:100%;overflow:hidden}iframe{display:block;width:100%;height:100%;border:0}</style>
</head><body><script>
(() => {
  const allowed = ${allowed};
  if (window.parent === window) return;
  let expected;
  try { expected = new URL(document.referrer).origin; } catch { return; }
  if (!allowed.includes(expected) || expected === location.origin) return;
  const view = document.createElement('iframe');
  view.title = 'MCP App';
  view.setAttribute('sandbox', 'allow-scripts allow-same-origin');
  document.body.append(view);
  let loaded = false;
  window.addEventListener('message', event => {
    if (event.source === window.parent && event.origin === expected) {
      const message = event.data;
      if (!message || message.jsonrpc !== '2.0') return;
      if (message.method === 'ui/notifications/sandbox-resource-ready') {
        if (loaded || typeof message.params?.html !== 'string' || message.params.html.length > 786432) return;
        loaded = true;
        const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
        view.srcdoc = '<!doctype html><meta http-equiv="Content-Security-Policy" content="' + policy + '">' + message.params.html;
      } else if (!message.method?.startsWith('ui/notifications/sandbox-') && loaded) {
        view.contentWindow.postMessage(message, location.origin);
      }
    } else if (event.source === view.contentWindow && event.origin === location.origin && loaded) {
      const message = event.data;
      if (message?.jsonrpc === '2.0' && !message.method?.startsWith('ui/notifications/sandbox-')) {
        window.parent.postMessage(message, expected);
      }
    }
  });
  window.parent.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/sandbox-proxy-ready', params: {} }, expected);
})();
</script></body></html>`;
}
