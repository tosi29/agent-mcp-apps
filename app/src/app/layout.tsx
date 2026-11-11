import type { Metadata } from "next";
import { connection } from "next/server";
import "@copilotkit/react-core/v2/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "データ探索室 | PoC",
  description: "会話から表形式データを検索・集計するプロトタイプ",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Prerendered pages emit duplicate x-nextjs-prerender headers in Next.js 16.4.
  // Web Adapter serializes duplicates as an array, which REST API streaming rejects.
  await connection();
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
