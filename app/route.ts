import shell from "../web/shell.html?raw";
import { getChatGPTUser, chatGPTSignInPath } from "./chatgpt-auth";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const user = await getChatGPTUser();
  if (!user) return Response.redirect(new URL(chatGPTSignInPath("/"), request.url), 302);
  return new Response(shell, {
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "private, no-store", "Vary": "Cookie" },
  });
}
