import { connection } from "next/server";
import { ExplorationChat } from "../components/exploration-chat";

export default async function Home() {
  await connection();
  return <ExplorationChat sandboxUrl={process.env.MCP_APPS_SANDBOX_URL} />;
}
