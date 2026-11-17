// The only MCP resource_link the UI follows: a result CSV saved by the exploration MCP server.
const RESULT_CSV_URI = /^exploration:\/\/results\/([0-9a-f]{32})\.csv$/;

export type ResultDownload = { uri: string; title: string; mimeType: "text/csv" };

export function resultCsvFilename(uri: string): string | undefined {
  const id = RESULT_CSV_URI.exec(uri)?.[1];
  return id ? `result-${id}.csv` : undefined;
}

export function resultCsvPath(uri: string): string {
  return `/api/resources?${new URLSearchParams({ uri })}`;
}
