// طبقة الاتصال بالخادم (API) — مركزية وقابلة لإعادة الاستخدام.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export const api = {
  status: () => request("/api/status"),
  capture: () => request("/api/capture", { method: "POST" }),
  captureWebcam: (image, opts = {}) =>
    request("/api/capture/webcam", {
      method: "POST",
      body: JSON.stringify({ image, ...opts }),
    }),
  print: () => request("/api/print", { method: "POST" }),
  cameraOrientation: () => request("/api/camera/orientation"),
  resetSession: (body) =>
    request("/api/session/reset", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
};
