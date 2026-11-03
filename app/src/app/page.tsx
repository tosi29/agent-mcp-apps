import { ExplorationChat } from "../components/exploration-chat";
import { connection } from "next/server";

export default async function Home() {
  await connection();
  return <ExplorationChat sandboxUrl={process.env.MCP_APPS_SANDBOX_URL} />;
}
