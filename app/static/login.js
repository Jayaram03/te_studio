// Sign-in page: password form, "Sign in with Google" (when set up), and messages from a refused Google sign-in.
document.querySelector(".dots").innerHTML = "<i></i>".repeat(36);
const f = document.getElementById("f"), err = document.getElementById("err"), go = document.getElementById("go");
const params = new URLSearchParams(location.search);
const safeNext = () => { const n = params.get("next"); return n && n.startsWith("/") && !n.startsWith("//") ? n : "/"; };
const MESSAGES = {
  not_admin: "That Google account isn't an admin here. Ask an admin to add your email in Settings → Team & sign-in.",
  disabled: "This account is disabled. Ask another admin to turn it back on.",
  expired: "The Google sign-in took too long or was interrupted. Please try again.",
  cancelled: "Google sign-in was cancelled.",
  unverified: "Your Google account's email isn't verified.",
  google_off: "Google sign-in isn't set up on this server.",
  failed: "Google sign-in didn't work. Please try again or use your password.",
};
function show(msg) { err.textContent = msg; err.style.display = "block"; }
if (params.get("error")) show(MESSAGES[params.get("error")] || MESSAGES.failed);
fetch("/api/auth/providers").then(r => r.json()).then(p => {
  if (!p.google) return;
  document.getElementById("google").classList.remove("hidden");
  document.getElementById("gbtn").href = "/auth/google/start?next=" + encodeURIComponent(safeNext() + location.hash);
}).catch(() => {});
document.getElementById("show").onclick = e => { const p = document.getElementById("password"); const s = p.type === "password"; p.type = s ? "text" : "password"; e.target.textContent = s ? "Hide" : "Show"; };
f.onsubmit = async e => {
  e.preventDefault(); err.style.display = "none"; go.disabled = true; go.textContent = "Signing in…";
  try {
    const r = await fetch("/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json", "X-Requested-With": "studio"},
      body: JSON.stringify({email: document.getElementById("email").value, password: document.getElementById("password").value})});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Could not sign in");
    const dest = safeNext();
    location.href = dest.includes("#") ? dest : dest + location.hash;   // keep e.g. #trips/12 from the original link
  } catch (x) { show(x.message); go.disabled = false; go.textContent = "Sign in"; }
};
