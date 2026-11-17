"use client";

import { useState } from "react";
import { appPath } from "../lib/paths";
import { type ResultDownload, resultCsvPath } from "../lib/result-csv";

// Reads the resource only when clicked, following the MCP resource_link.
export function ResultDownloads({ downloads }: { downloads: ResultDownload[] }) {
  const [state, setState] = useState<{ busy?: string; error?: string }>({});

  const download = async (uri: string, filename: string) => {
    setState({ busy: uri });
    try {
      const response = await fetch(appPath(resultCsvPath(uri)), { cache: "no-store" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? "CSVを取得できません。");
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setState({});
    } catch (error) {
      setState({ error: (error as Error).message });
    }
  };

  return (
    <div className="result-downloads">
      {downloads.map((link) => (
        <button
          key={link.uri}
          type="button"
          className="download-button"
          title={link.title}
          disabled={state.busy === link.uri}
          onClick={() => download(link.uri, link.name)}
        >
          {state.busy === link.uri ? "取得中…" : "CSVをダウンロード"}
        </button>
      ))}
      {state.error && (
        <span className="small-note download-error" role="alert">
          {state.error}
        </span>
      )}
    </div>
  );
}
