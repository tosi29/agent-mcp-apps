"use client";

import { useState } from "react";
import { appPath } from "../lib/paths";
import { type ResultDownload, resultCsvFilename, resultCsvPath } from "../lib/result-csv";

// Reads the resource only when clicked, following the MCP resource_link.
export function ResultDownloads({ downloads }: { downloads?: ResultDownload[] }) {
  const [state, setState] = useState<{ busy?: string; error?: string }>({});
  const links = (downloads ?? []).flatMap((link) => {
    const filename = resultCsvFilename(link.uri);
    return filename ? [{ ...link, filename }] : [];
  });
  if (links.length === 0) return null;

  const download = async (uri: string, filename: string) => {
    setState({ busy: uri });
    try {
      const response = await fetch(appPath(resultCsvPath(uri)), { cache: "no-store" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.error === "string" ? body.error : "CSVを取得できません。");
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setState({});
    } catch (error) {
      setState({ error: error instanceof Error ? error.message : "CSVを取得できません。" });
    }
  };

  return (
    <div className="result-downloads">
      {links.map((link) => (
        <button
          key={link.uri}
          type="button"
          className="download-button"
          title={link.title}
          disabled={state.busy === link.uri}
          onClick={() => download(link.uri, link.filename)}
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
