import type { Metadata } from "next";
import "@copilotkit/react-core/v2/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "データ探索室 | ローカルPoC",
  description: "会話から表形式データを検索・集計するローカルプロトタイプ",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ja"><body>{children}</body></html>;
}
