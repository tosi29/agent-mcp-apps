"use client";

import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import { useEffect, useRef, useState } from "react";
import type { McpAppResult } from "../lib/result-history";

export function McpAppResultView({ app, sandboxUrl }: { app: McpAppResult; sandboxUrl?: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [status, setStatus] = useState("MCP Appを読み込んでいます…");

  useEffect(() => {
    const iframe = frame.current;
    if (!iframe) return;
    const configured = sandboxUrl ?? process.env.NEXT_PUBLIC_MCP_APPS_SANDBOX_URL;
    if (!configured) {
      setStatus("MCP Appsのsandbox URLが設定されていません。");
      return;
    }
    let sandbox: URL;
    try {
      sandbox = new URL(configured);
      if (
        sandbox.origin === window.location.origin ||
        sandbox.username ||
        sandbox.password ||
        !(
          sandbox.protocol === "https:" ||
          (sandbox.protocol === "http:" && ["127.0.0.1", "localhost"].includes(sandbox.hostname))
        )
      ) {
        throw new Error("invalid sandbox");
      }
    } catch {
      setStatus("sandboxには画面と別オリジンのHTTPS URL、またはローカルURLを指定してください。");
      return;
    }
    const bridge = new AppBridge(
      null,
      { name: "データ探索室", version: "1.0.0" },
      {},
      {
        hostContext: {
          theme: "light",
          displayMode: "inline",
          availableDisplayModes: ["inline"],
          locale: "ja-JP",
        },
      },
    );
    let disposed = false;
    let initialized = false;
    const timer = setTimeout(() => {
      if (!disposed) setStatus("MCP Appへの接続がタイムアウトしました。");
    }, 15_000);
    const fail = () => {
      if (!disposed) setStatus("MCP Appの表示に失敗しました。");
    };
    // This read-only host grants no tool calls, chat messages, context updates or links.
    const denied = async () => {
      throw new Error("このホストでは許可されていない操作です");
    };
    bridge.onmessage = denied;
    bridge.onupdatemodelcontext = denied;
    bridge.onopenlink = denied;
    bridge.oncalltool = denied;
    bridge.onsizechange = ({ height }) => {
      if (typeof height === "number" && Number.isFinite(height))
        iframe.style.height = `${Math.max(240, Math.min(900, height))}px`;
    };
    bridge.oninitialized = () => {
      if (disposed || initialized) return;
      initialized = true;
      clearTimeout(timer);
      void (async () => {
        await bridge.sendToolInput({ arguments: app.toolInput });
        await bridge.sendToolResult(app.toolResult);
        if (!disposed) setStatus("");
      })().catch(fail);
    };
    // The SDK transport checks the source window; also check the proxy's origin.
    const originGuard = (event: MessageEvent) => {
      if (event.source === iframe.contentWindow && event.origin !== sandbox.origin)
        event.stopImmediatePropagation();
    };
    window.addEventListener("message", originGuard);
    const ready = (event: MessageEvent) => {
      if (
        event.source !== iframe.contentWindow ||
        event.origin !== sandbox.origin ||
        event.data?.method !== "ui/notifications/sandbox-proxy-ready"
      )
        return;
      window.removeEventListener("message", ready);
      void (async () => {
        await bridge.connect(
          new PostMessageTransport(iframe.contentWindow!, iframe.contentWindow!),
        );
        if (!disposed)
          await bridge.sendSandboxResourceReady({
            html: app.html,
            csp: { connectDomains: [], resourceDomains: [], frameDomains: [] },
          });
      })().catch(fail);
    };
    window.addEventListener("message", ready);
    iframe.src = sandbox.href;
    return () => {
      disposed = true;
      clearTimeout(timer);
      window.removeEventListener("message", ready);
      window.removeEventListener("message", originGuard);
      void (async () => {
        try {
          if (initialized) await bridge.teardownResource({}, { timeout: 1000 });
        } catch {
          /* A detached frame cannot acknowledge teardown. */
        } finally {
          await bridge.close();
        }
      })();
    };
  }, [app, sandboxUrl]);

  return (
    <div className="mcp-app-result" data-testid="mcp-app-result">
      {status && (
        <p className="small-note" role="status">
          {status}
        </p>
      )}
      <iframe
        ref={frame}
        title="MCP App：取引ダッシュボード"
        sandbox="allow-scripts allow-same-origin"
        referrerPolicy="origin"
        className="mcp-app-frame"
      />
    </div>
  );
}
