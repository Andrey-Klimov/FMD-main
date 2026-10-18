import { getChatGPTUser, chatGPTSignInPath, chatGPTSignOutPath } from "../../chatgpt-auth";

export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getChatGPTUser();
  return Response.json({
    authenticated: Boolean(user),
    user: user ? { displayName: user.displayName, email: user.email } : null,
    signInUrl: chatGPTSignInPath("/"),
    signOutUrl: chatGPTSignOutPath("/"),
  }, { headers: { "Cache-Control": "private, no-store", "Vary": "Cookie" } });
}
