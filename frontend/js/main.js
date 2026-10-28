// نقطة دخول الواجهة.
// الخطوة ٤: تدفق الالتقاط + الطباعة + إدارة الجلسة.

import { Router } from "./router.js";
import { CaptureFlow } from "./flow.js";
import { initTouchSerial } from "./touch-serial.js";

const router = new Router();
const flow = new CaptureFlow(router);
const hero = document.getElementById("attract-hero");

/** عند لمس شاشة الانتظار: عرض خيارات مدة المؤقت. */
function startSession() {
  flow.noteActivity();
  hero.classList.add("is-pressed");
  hero.addEventListener(
    "animationend",
    () => hero.classList.remove("is-pressed"),
    { once: true }
  );
  setTimeout(() => flow.showChooser(), 260);
}

async function init() {
  router.show("attract");
  // مهم: نختار قسم الشاشة تحديداً (.screen) لا الحاوية، وإلا التصق المستمع بكل الشاشة.
  document
    .querySelector('.screen[data-screen="attract"]')
    .addEventListener("pointerdown", startSession);

  // لمس شاشة التوقّف يُغلقها ويعيد لشاشة الانتظار.
  document
    .querySelector('.screen[data-screen="screensaver"]')
    .addEventListener("pointerdown", () => flow.dismissScreensaver());

  // مراقبة دورية: تُقفل الشاشة تلقائياً عند اكتمال الجلسة/انتهاء الوقت/الإيقاف،
  // وتفتحها عند بدء مناسبة جديدة — دون تدخّل يدوي.
  flow.startPolling(5000);

  // طبقة اللمس الافتراضية (حسّاسا ToF عبر Web Serial). آمنة: تُتجاهل بهدوء
  // إن لم يتوفّر المتصفّح الداعم أو الجهاز. راجع docs/tof-touch-overlay.md.
  initTouchSerial();
}

init();
