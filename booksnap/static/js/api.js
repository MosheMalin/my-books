/* Thin fetch wrapper: unwraps FastAPI's {"detail": ...} error shape so callers
   can just catch and show e.message. */

export const api = async (url, opt) => {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};

export const jsonReq = (method, body) => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
});
