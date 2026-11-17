import { allowedOrigin } from "../../../lib/backend";
import { mcpConfigured, ResourceUnavailableError, readResultCsv } from "../../../lib/mcp-resources";
import { resultCsvFilename } from "../../../lib/result-csv";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Follows a resource_link with MCP resources/read. Rows never pass through the model.
export async function GET(request: Request) {
  if (!allowedOrigin(request)) {
    return Response.json({ error: "origin not allowed" }, { status: 403 });
  }
  const uri = new URL(request.url).searchParams.get("uri") ?? "";
  const filename = resultCsvFilename(uri);
  if (!filename) {
    return Response.json({ error: "対応していないリソースです。" }, { status: 400 });
  }
  if (!mcpConfigured()) {
    return Response.json({ error: "MCPサーバーが設定されていません。" }, { status: 501 });
  }
  try {
    const csv = await readResultCsv(uri);
    // The BOM lets spreadsheet apps detect UTF-8 for Japanese text.
    return new Response(`﻿${csv}`, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof ResourceUnavailableError) {
      return Response.json(
        { error: "CSVを取得できません。結果の保存期限が過ぎた可能性があります。" },
        { status: 404 },
      );
    }
    return Response.json({ error: "MCPサーバーに接続できません。" }, { status: 502 });
  }
}
