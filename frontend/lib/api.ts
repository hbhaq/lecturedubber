export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export function csrfToken() {
  return csrf;
}
export async function api(path: string, method = "GET", body?: unknown) {
  const headers: Record<string, string> = {};
  if (!(body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (!["GET", "HEAD"].includes(method) && csrf) headers["X-CSRF-Token"] = csrf;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  let r: Response;
  try { r = await fetch(API + path, {
    signal: controller.signal,
    method,
    credentials: "include",
    headers,
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
  }); } catch (e) {
    if (controller.signal.aborted) throw Error("Server did not respond within 20 seconds. Background processing may still be running; refresh status.");
    throw e;
  } finally { clearTimeout(timer); }
  if (!r.ok) {
    if (
      r.status === 401 &&
      path != "/auth/login" &&
      typeof window !== "undefined"
    )
      window.dispatchEvent(new Event("session-expired"));
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return r.json();
}
