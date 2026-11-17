import { agentRuntimeArn } from "../../../lib/agentcore";
import { agentUrl, allowedOrigin } from "../../../lib/backend";
import { resultCsvFilename } from "../../../lib/result-csv";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Follows a resource_link through the agent backend. Rows never pass through the model.
export async function GET(request: Request) {
  if (!allowedOrigin(request)) {
    return Response.json({ error: "origin not allowed" }, { status: 403 });
  }
  const uri = new URL(request.url).searchParams.get("uri") ?? "";
  const filename = resultCsvFilename(uri);
  if (!filename) {
    return Response.json({ error: "対応していないリソースです。" }, { status: 400 });
  }
  if (agentRuntimeArn()) {
    return Response.json(
      { error: "クラウド構成ではCSVのダウンロードに対応していません。" },
      { status: 501 },
    );
  }
  try {
    const upstream = await fetch(
      new URL(`/resources/read?${new URLSearchParams({ uri })}`, agentUrl()),
      {
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (!upstream.ok) {
      return Response.json(
        { error: "CSVを取得できません。結果の保存期限が過ぎた可能性があります。" },
        { status: upstream.status === 404 ? 404 : 502 },
      );
    }
    // The BOM lets spreadsheet apps detect UTF-8 for Japanese text.
    return new Response(`﻿${await upstream.text()}`, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return Response.json({ error: "エージェントに接続できません。" }, { status: 502 });
  }
}
