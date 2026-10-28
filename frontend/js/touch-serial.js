// ============================================================================
// طبقة اللمس الافتراضية — جانب الواجهة — نسخة الحسّاس الواحد
// حسّاس ToF واحد في أسفل الإطار يصوّب للأعلى. مسافته = الموضع على المحور الرأسي (Y).
// لا محور X: النقرة تُحقن عند منتصف العرض (nx=0.5)، فتصيب الأزرار العريضة العمودية.
// تملك هذه الوحدة: المعايرة (أعلى/أسفل) + كشف الدخول + إزالة الارتداد + حقن المؤشّر.
//
// النقل: الباك-إند يقرأ المنفذ التسلسلي ويبثّ الإطارات الخام عبر SSE على
// /api/touch/stream — لأن كروميوم-snap على البوث لا يفتح /dev/ttyACM0 عبر Web Serial.
// نستهلكها عبر EventSource. تبقى المعايرة كلّها هنا (بلا إعادة فلاش للمتحكّم).
//
// التفعيل: استيراد واحد في main.js. يفشل بهدوء إن لم يتوفّر البثّ.
// وضع المعايرة/التشخيص: افتح الكيوسك بـ ?cal=1 لعرض HUD وأوامر معايرة في console.
//
// البروتوكول المبثوث من الباك-إند:  R,<d_mm>,<v>   و   S,ready / S,err
// راجع docs/tof-touch-overlay.md.
// ============================================================================

const STREAM_URL = "/api/touch/stream";
const STORAGE_KEY = "qamra.touchcal.single";

// عتبات منطق اللمس (قابلة للضبط من console عبر window.qamraTouch.tune).
// نموذج الكشف (مثبّت ميدانياً 2026-10-24): المشهد الفارغ = valid=0 (لا عاكس ضمن المدى)،
// ووجود يد = valid=1 ضمن بوابة المدى. لذا: «يوجد يد» = valid && minMm ≤ d ≤ maxMm.
// (لا نستخدم خطّ أساس لأن الفارغ لا يُعطي قراءة بعيدة ثابتة في هذا التركيب.)
const cfg = {
  minMm: 80,        // مل‌م: أقرب مسافة نقبلها (أقلّ = ضجيج/حافة الإطار)
  // مل‌م: أبعد مسافة نقبلها. القمّة في الشاشة الطولية ≈ ١٣٨٥مم (وضع Long يغطّي ~٥٠–١٤٠٠)،
  // فلا بدّ أن تتجاوزها البوابة وإلا رُفضت نقطة المعايرة العليا؛ وتبقى دون خلفية ~٢٧٠٠مم.
  maxMm: 1500,      // (قيمة مثبّتة ميدانياً على البوث — راجع docs/touch_cal.booth.json)
  pressFrames: 3,   // إطارات حضور متتالية قبل اعتماد الضغط (down)
  releaseFrames: 8, // إطارات غياب متتالية قبل اعتماد التحرّر (up) — هامش ضدّ الانقطاع اللحظي
  cooldownMs: 450,  // تهدئة بعد كل نقرة (تمنع نقرة ثانية فورية)
  nx: 0.5,          // الموضع الأفقي الثابت للنقرة (منتصف العرض)
};

// المعايرة:
//   points = نقاط [{d: مسافة‌مم, ny: موضع‌رأسي 0..1}] من روتين المعايرة التفاعلي —
//            المصدر الأدقّ: خريطة خطّية بالقطع تتحمّل اللاخطّية. تُجلب من الخادم.
//   dTop/dBottom = خريطة نقطتين احتياطية إن لم تتوفّر points.
let cal = loadCal() || { points: [], dTop: 470, dBottom: 85 };

// حالة التشغيل.
const state = {
  present: false,          // أهناك يد ضمن المدى الآن؟
  downFrames: 0, upFrames: 0,
  touching: false,
  lastNy: cfg.nx,          // آخر موضع رأسي صالح (نَنقر عنده عند الانسحاب)
  lastRaw: { d: 0, v: 0 },
  seq: 0,                  // عدّاد يتزايد مع كل إطار وارد (لتمييز الإطار الجديد في المعايرة)
  cooldownUntil: 0,        // لا نبدأ ضغطاً جديداً قبل هذا الوقت (تهدئة بعد النقرة)
};

let calibrating = false;   // أثناء روتين المعايرة: نوقف حقن النقر ونلتقط العيّنات فقط
let loadedRev = null;      // رقم إصدار JS المحمّل (لإعادة التحميل الذاتي عند رفعه)

let onStatus = () => {};

// ---- الدخول ----------------------------------------------------------------

/**
 * تشغيل طبقة اللمس. آمنة الاستدعاء دائماً: تعود بهدوء إن لم يتوفّر EventSource.
 * تتّصل ببثّ SSE من الباك-إند؛ EventSource يعيد الاتصال تلقائياً عند الانقطاع.
 * @param {{onStatus?: (s:string)=>void}} opts
 */
export function initTouchSerial(opts = {}) {
  onStatus = opts.onStatus || onStatus;
  if (typeof EventSource === "undefined") {
    console.info("[touch] EventSource غير مدعوم — تُتجاهل طبقة اللمس.");
    return;
  }
  if (isCalMode()) mountHud();
  exposeConsoleApi();
  syncCal();                          // اجلب المعايرة من الخادم فوراً
  setInterval(syncCal, 3000);         // وأعد جلبها دورياً (ضبط لحظي من البوث بلا إعادة تحميل)
  connect();
}

// يجلب المعايرة من الباك-إند (المصدر الموثوق على الكيوسك)، ويبدأ روتين المعايرة
// حين يرفع المشغّل العلم calibrate. فشل الجلب يُبقي القيم الحالية (آمن).
async function syncCal() {
  try {
    const r = await fetch("/api/touch/cal", { cache: "no-store" });
    if (!r.ok) return;
    const s = await r.json();
    // إعادة تحميل ذاتية: رفع rev من الخادم يعيد تحميل الكيوسك (لتفعيل JS جديد بلا إقلاع).
    const rev = Number.isFinite(s.rev) ? s.rev : 0;
    if (loadedRev === null) loadedRev = rev;
    else if (rev > loadedRev) { location.reload(); return; }
    // لا نكتب المعايرة فوق نفسها أثناء الروتين (نبنيها محلياً ثم نرسلها في النهاية).
    if (!calibrating) {
      if (Array.isArray(s.points)) cal.points = s.points;
      if (Number.isFinite(s.dTop)) cal.dTop = s.dTop;
      if (Number.isFinite(s.dBottom)) cal.dBottom = s.dBottom;
      if (Number.isFinite(s.minMm)) cfg.minMm = s.minMm;
      if (Number.isFinite(s.maxMm)) cfg.maxMm = s.maxMm;
      if (Number.isFinite(s.pressFrames)) cfg.pressFrames = s.pressFrames;
      if (Number.isFinite(s.releaseFrames)) cfg.releaseFrames = s.releaseFrames;
      if (Number.isFinite(s.cooldownMs)) cfg.cooldownMs = s.cooldownMs;
    }
    if (s.calibrate === true && !calibrating) runCalibration();
  } catch {
    /* بلا شبكة/خادم — أبقِ القيم الحالية */
  }
}

// إرسال المعايرة/العلم للخادم (من الكيوسك محلياً — بلا PIN).
async function postCal(body) {
  try {
    await fetch("/api/touch/cal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    /* تجاهل */
  }
}

// فتح بثّ SSE. EventSource يتكفّل بإعادة المحاولة تلقائياً.
function connect() {
  let es;
  try {
    es = new EventSource(STREAM_URL);
  } catch (e) {
    console.warn("[touch] تعذّر فتح البثّ:", e);
    return;
  }
  es.onopen = () => onStatus("connected");
  es.onerror = () => {
    // قد ينقطع البثّ أثناء لمسة قائمة: نُلغيها فوراً، وإلا أطلقت إطاراتُ الغياب بعد
    // إعادة الاتصال نقرةً مؤجّلة عند الموضع القديم (قد تكون طباعة غير مقصودة في شاشة
    // النتيجة). إعادة الاتصال لا تأتي بـS,ready فلا تصفير تلقائي من البروتوكول.
    resetTouch();
    onStatus("reconnecting"); // EventSource يعيد المحاولة تلقائياً
  };
  es.onmessage = (ev) => {
    const line = (ev.data || "").trim();
    if (line) handleLine(line);
  };
}

// ---- تحليل البروتوكول ------------------------------------------------------

function handleLine(line) {
  const parts = line.split(",");
  if (parts[0] === "R" && parts.length >= 3) {
    const d = +parts[1], v = +parts[2];
    if (Number.isFinite(d)) onFrame(d, v);
  } else if (parts[0] === "S") {
    onStatus(parts.slice(1).join(",") || parts[0]);
    if (parts[1] === "ready") resetTouch();
  }
}

// ---- منطق اللمس (محور واحد) ------------------------------------------------

function onFrame(d, v) {
  state.lastRaw = { d, v };
  state.seq++;  // إطار جديد وصل (قبل أي تفرّع) — تعتمد عليه المعايرة لعدّ الإطارات الطازجة

  // أثناء المعايرة لا نحقن نقراً — الروتين يلتقط العيّنات من state.lastRaw مباشرةً.
  if (calibrating) { updateHud(); return; }

  // «يوجد يد» = قياس صالح ضمن بوابة المدى. المشهد الفارغ يأتي valid=0 فيُرفض.
  const present = v === 1 && d >= cfg.minMm && d <= cfg.maxMm;
  state.present = present;

  if (present) {
    state.downFrames++;
    state.upFrames = 0;
    state.lastNy = mapToNy(d);   // احفظ آخر موضع صالح للنقر عند الانسحاب
  } else {
    state.upFrames++;
    state.downFrames = 0;
  }

  const now = performance.now();
  if (!state.touching && state.downFrames >= cfg.pressFrames && now >= state.cooldownUntil) {
    // بدأت لمسة — لا نرسل شيئاً الآن (نتجنّب تقسيم الحدث عبر الزمن/تغيّر الشاشة).
    state.touching = true;
  } else if (state.touching && state.upFrames >= cfg.releaseFrames) {
    // تحرّر بعد غياب مستمرّ (releaseFrames) — الانقطاع اللحظي القصير لا يُنهي اللمسة.
    // نقرة واحدة ذرّية عند آخر موضع صالح (عند أعلى عنصر هناك).
    state.touching = false;
    tap(cfg.nx, state.lastNy);
    state.cooldownUntil = now + cfg.cooldownMs;  // تهدئة تمنع نقرة ثانية فورية
  }

  updateHud();
}

function resetTouch() {
  state.touching = false;
  state.present = false;
  state.downFrames = state.upFrames = 0;
}

// تحويل المسافة → الموضع الرأسي ny (0=أعلى، 1=أسفل).
// أولوية: خريطة خطّية بالقطع عبر نقاط المعايرة (مرتّبة حسب d تصاعدياً)؛ وإلا نقطتان.
function mapToNy(d) {
  const pts = cal.points;
  if (!pts || pts.length < 2) {
    return clamp01((cal.dTop - d) / (cal.dTop - cal.dBottom));
  }
  if (d <= pts[0].d) return clamp01(pts[0].ny);
  const last = pts[pts.length - 1];
  if (d >= last.d) return clamp01(last.ny);
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    if (d >= a.d && d <= b.d) {
      const t = (b.d === a.d) ? 0 : (d - a.d) / (b.d - a.d);
      return clamp01(a.ny + t * (b.ny - a.ny));
    }
  }
  return clamp01(pts[0].ny);
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

// ---- حقن النقرة ------------------------------------------------------------

// نقرة واحدة ذرّية: نلتقط العنصر عند (nx,ny) مرّة واحدة ونرسل له التسلسل كاملاً
// (pointerdown→pointerup→click) إلى **نفس** العنصر. هذا يمنع:
//   - الازدواج (حدث واحد لكل لمسة).
//   - تتالي الشاشات: لو بدّل pointerdown الشاشة (شاشة الانتظار)، تبقى بقية الأحداث
//     على العنصر الأصلي الملتَقَط، فلا تسقط النقرة على الشاشة الجديدة.
function tap(nx, ny) {
  const x = Math.round(nx * window.innerWidth);
  const y = Math.round(ny * window.innerHeight);
  const el = document.elementFromPoint(x, y);
  if (!el) return;
  const base = {
    clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerType: "touch", isPrimary: true, pointerId: 1,
  };
  el.dispatchEvent(new PointerEvent("pointerdown", base));
  el.dispatchEvent(new PointerEvent("pointerup", base));
  el.dispatchEvent(new MouseEvent("click", base));
}

// ---- المعايرة ---------------------------------------------------------------

function loadCal() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}
function saveCal() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cal));
  } catch {}
}

// ---- روتين المعايرة التفاعلي (على شاشة البوث) ------------------------------
// أفضل ممارسة: نعرض أهدافاً عند مواضع رأسية معلومة، نطلب لمس كلٍّ، نلتقط مسافة
// الحسّاس عندها، ثم نبني خريطة خطّية بالقطع (مسافة→ny). يبدأ حين يرفع المشغّل العلم
// calibrate (POST /api/touch/cal). يُرسل النقاط للخادم في النهاية فتسري على الكيوسك.

const CAL_YFRACS = [0.12, 0.3, 0.5, 0.7, 0.88]; // مواضع الأهداف (نسبة من الارتفاع)
const CAL_PREP_MS = 2600;   // مهلة وضع اليد قبل القياس
const CAL_HOLD_MS = 1800;   // مدّة القياس (ثبات اليد)
const CAL_MIN_SAMPLES = 8;  // أقلّ عيّنات صالحة لاعتماد الهدف

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function runCalibration() {
  if (calibrating) return;
  calibrating = true;
  resetTouch();
  const ui = buildCalUi();
  const collected = [];
  try {
    for (let i = 0; i < CAL_YFRACS.length; i++) {
      const yf = CAL_YFRACS[i];
      ui.setTarget(yf, i + 1, CAL_YFRACS.length);
      ui.setPhase("استعدّ… ضع إصبعك عند الدائرة");
      await countdown(ui, CAL_PREP_MS);
      ui.setPhase("لا تحرّك يدك — جارٍ القياس");
      const d = await captureMedian(CAL_HOLD_MS, ui);
      if (d != null) {
        collected.push({ d, ny: yf });
        ui.flashOk();
      } else {
        ui.flashSkip();
      }
      await wait(350);
    }
    // رتّب حسب d تصاعدياً (d يكبر كلّما ارتفعت اليد)، وأزل التكرار/غير المرتّب.
    const pts = dedupeMonotonic(collected);
    if (pts.length >= 2) {
      cal.points = pts;
      saveCal();
      await postCal({ points: pts, calibrate: false });
      ui.done(`تمّت المعايرة (${pts.length} نقاط)`);
    } else {
      await postCal({ calibrate: false });
      ui.done("فشلت المعايرة — لم تُقرأ نقاط كافية");
    }
  } finally {
    await wait(1600);
    ui.remove();
    calibrating = false;
    resetTouch();
  }
}

// يلتقط وسيط المسافة للعيّنات الصالحة خلال ms (يقرأ آخر إطار حيّ من البثّ).
async function captureMedian(ms, ui) {
  const vals = [];
  let lastSeq = state.seq;  // لا نعدّ إلا الإطارات الطازجة: لو توقّف البثّ لا تتراكم
  const end = performance.now() + ms;
  while (performance.now() < end) {
    if (state.seq !== lastSeq) {  // وصل إطار جديد منذ آخر فحص فقط
      lastSeq = state.seq;
      const r = state.lastRaw;
      if (r.v === 1 && r.d >= cfg.minMm && r.d <= cfg.maxMm) vals.push(r.d);
    }
    if (ui) ui.setProgress((ms - (end - performance.now())) / ms);
    await wait(40);
  }
  if (vals.length < CAL_MIN_SAMPLES) return null;
  vals.sort((a, b) => a - b);
  return vals[Math.floor(vals.length / 2)];
}

// يضمن ترتيباً تصاعدياً صارماً على d (يحذف ما يكسر الرتابة ليصحّ الاستيفاء).
function dedupeMonotonic(points) {
  const sorted = points.slice().sort((a, b) => a.d - b.d);
  const out = [];
  for (const p of sorted) {
    if (out.length === 0 || p.d > out[out.length - 1].d) out.push(p);
  }
  return out;
}

async function countdown(ui, ms) {
  const end = performance.now() + ms;
  while (performance.now() < end) {
    ui.setCount(Math.ceil((end - performance.now()) / 1000));
    await wait(100);
  }
}

// واجهة المعايرة: تراكب ملء الشاشة بهدف دائري متحرّك + تعليمات + مؤشّر تقدّم.
function buildCalUi() {
  const root = document.createElement("div");
  Object.assign(root.style, {
    position: "fixed", inset: "0", zIndex: "100000",
    background: "rgba(0,0,0,0.96)", color: "#f1ece1",
    font: "500 min(4.5vh,28px)/1.5 system-ui, sans-serif", textAlign: "center",
  });
  const phase = document.createElement("div");
  Object.assign(phase.style, { position: "absolute", top: "6%", left: "0", right: "0", padding: "0 6%" });
  const count = document.createElement("div");
  Object.assign(count.style, { position: "absolute", bottom: "10%", left: "0", right: "0", font: "600 min(9vh,64px)/1 system-ui", opacity: "0.9" });
  const step = document.createElement("div");
  Object.assign(step.style, { position: "absolute", bottom: "5%", left: "0", right: "0", opacity: "0.6", font: "400 min(3vh,18px)/1 system-ui" });
  const target = document.createElement("div");
  Object.assign(target.style, {
    position: "absolute", left: "50%", width: "min(26vw,150px)", height: "min(26vw,150px)",
    transform: "translate(-50%,-50%)", borderRadius: "50%",
    border: "4px solid #f1ece1", boxShadow: "0 0 0 6px rgba(241,236,225,0.15)",
    display: "flex", alignItems: "center", justifyContent: "center",
    transition: "top 0.35s ease, background 0.2s, border-color 0.2s",
  });
  const dot = document.createElement("div");
  Object.assign(dot.style, { width: "18%", height: "18%", borderRadius: "50%", background: "#f1ece1" });
  target.appendChild(dot);
  root.append(phase, target, count, step);
  document.body.appendChild(root);
  return {
    setTarget(yf, i, n) {
      target.style.top = (yf * 100) + "%";
      step.textContent = `نقطة ${i} من ${n}`;
      target.style.borderColor = "#f1ece1";
      target.style.background = "transparent";
    },
    setPhase: (t) => { phase.textContent = t; },
    setCount: (s) => { count.textContent = s > 0 ? String(s) : ""; },
    setProgress: (p) => { count.textContent = Math.round(p * 100) + "%"; },
    flashOk: () => { target.style.background = "rgba(120,220,140,0.35)"; target.style.borderColor = "#7cdc8c"; },
    flashSkip: () => { target.style.background = "rgba(220,120,120,0.35)"; target.style.borderColor = "#dc7c7c"; },
    done: (t) => { phase.textContent = t; count.textContent = ""; step.textContent = ""; },
    remove: () => root.remove(),
  };
}

// ---- واجهة console للمشغّل --------------------------------------------------
// إجراء المعايرة على البوث:
//   1) ضع اليد عند أعلى منطقة الأزرار ثم: qamraTouch.markTop()
//   2) ضع اليد عند أسفل منطقة الأزرار ثم: qamraTouch.markBottom()
//   3) جرّب؛ اضبط بوابة المدى عند الحاجة: qamraTouch.tune({minMm: 100, maxMm: 900})

function exposeConsoleApi() {
  window.qamraTouch = {
    raw: () => ({ ...state.lastRaw, present: state.present, ny: state.lastNy }),
    getCal: () => ({ ...cal }),
    setCal: (obj) => { Object.assign(cal, obj); saveCal(); return cal; },
    // ضبط يدوي بنقطتين: نمسح نقاط الخمس-نقاط (وإلا تجاهلها mapToNy) ونثبّت القيمة على
    // الخادم (POST) حتى لا يُعيدها sync التالي من القيم المحفوظة.
    markTop:    () => { cal.points = []; cal.dTop    = state.lastRaw.d; saveCal(); postCal({ points: [], dTop: cal.dTop }); return cal; },
    markBottom: () => { cal.points = []; cal.dBottom = state.lastRaw.d; saveCal(); postCal({ points: [], dBottom: cal.dBottom }); return cal; },
    tune: (obj) => { Object.assign(cfg, obj); return { ...cfg }; },
    reset: () => { resetTouch(); return "أُعيد ضبط حالة اللمس"; },
    calibrate: () => { runCalibration(); return "بدأ روتين المعايرة"; },
  };
}

// ---- HUD التشخيص (المشغّل فقط، عبر ?cal=1) ----------------------------------

function isCalMode() {
  return new URLSearchParams(location.search).has("cal");
}

let hud = null;
function mountHud() {
  hud = document.createElement("div");
  hud.id = "touch-hud";
  Object.assign(hud.style, {
    position: "fixed", top: "8px", left: "8px", zIndex: 99999,
    font: "12px/1.5 monospace", color: "#0f0", background: "rgba(0,0,0,.8)",
    padding: "8px 10px", borderRadius: "8px", whiteSpace: "pre", pointerEvents: "none",
  });
  document.body.appendChild(hud);
}
function updateHud() {
  if (!hud) return;
  const r = state.lastRaw;
  const pts = (cal.points && cal.points.length)
    ? cal.points.map((p) => `${p.d}:${p.ny}`).join(" ")
    : `2pt ${cal.dBottom}-${cal.dTop}`;
  hud.textContent =
    `d=${r.d} v=${r.v}  gate=${cfg.minMm}-${cfg.maxMm}\n` +
    `present=${state.present ? 1 : 0}  touch=${state.touching ? 1 : 0}  cal=${calibrating ? 1 : 0}\n` +
    `pts ${pts}\n` +
    `ny=${state.lastNy.toFixed(2)}`;
}
