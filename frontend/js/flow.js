// تدفق الالتقاط والطباعة والمشاركة:
// انتظار ← عدّاد ← فلاش ← التقاط ← نتيجة (اطبع / نسخة رقمية / أعد) ← تأكيد ← انتظار.
//
// ملاحظة UX: لا تُعرض أي معلومات تشغيلية (المتبقي/الوقت) للضيف — هي للمشغّل فقط.

import { api } from "./api.js";
import { Camera } from "./camera.js";
import { wait } from "./helpers.js";

const DEFAULT_COUNTDOWN = 5;
const IDLE_MS = 60000; // عودة تلقائية إذا ترك الضيف الشاشة
const SCREENSAVER_MS = 120000; // دقيقتان بلا لمس على شاشة الانتظار → شاشة التوقّف

export class CaptureFlow {
  constructor(router) {
    this.router = router;
    this.countdownEl = document.getElementById("countdown");
    this.countdownRing = document.getElementById("countdown-ring");
    this.promptEl = document.getElementById("capture-prompt");
    this.photoEl = document.getElementById("result-photo");
    this.overlayEl = document.getElementById("result-overlay");
    this.optionsEl = document.getElementById("chooser-options");
    this.printBtn = document.getElementById("btn-print");

    this.busy = false;
    this.remaining = null; // داخلي فقط — لا يُعرض للضيف
    this.paused = false;
    this.settings = {};
    this.idleTimer = null;

    // شاشة التوقّف (ثيم المناسبة): تظهر بعد خمول على شاشة الانتظار
    this.screensaverImg = document.getElementById("screensaver-img");
    this.screensaverUrl = ""; // رابط الصورة ("" = الميزة معطّلة)
    this.lastActivity = Date.now();

    // مصدر الكاميرا (يُحدّث من حالة الخادم): webcam | mock | gphoto2
    this.cameraMode = "mock";
    this.camera = new Camera();
    this.videoEl = document.getElementById("cam-video");
    this.previewImg = document.getElementById("cam-preview"); // بثّ Live View (gphoto2)
    this.overlayImg = null; // صورة الإطار (تُدمج في الصورة الملتقطة)
    this.brandMark = null; // قفل العلامة الأفقي الجاهز لشريط اللوقو السفلي (يُدمج في كل صورة)

    this.printBtn.addEventListener("click", () => this.#onPrint());
    document
      .getElementById("btn-home")
      .addEventListener("click", () => this.#onHome());

    // اختيار مدة المؤقت (تفويض الحدث — الأزرار تُبنى ديناميكياً)
    this.optionsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".timer-opt");
      if (btn) this.run(parseInt(btn.dataset.seconds, 10) || DEFAULT_COUNTDOWN);
    });
  }

  /** تطبيق الإعدادات على واجهة الضيف. */
  applySettings(settings) {
    this.settings = settings || {};

    // إظهار/إخفاء الطباعة
    this.printBtn.hidden = this.settings.print_enabled === false;

    // عند إلغاء الإطار نُسقط النسخة المحمّلة (تُعاد عند الحاجة)
    if (!this.settings.overlay) this.overlayImg = null;

    // رابط شاشة التوقّف (ثيم المناسبة) — "" يعطّل الميزة
    this.screensaverUrl = this.settings.screensaver || "";

    // قلب الصورة أفقياً للعرض — في وضعَي الكاميرا الحقيقية (webcam/gphoto2) يكون
    // القلب مدموجاً في الصورة نفسها، فلا نكرّره كطبقة عرض حتى لا ينقلب مرتين.
    const cssMirror =
      !this.#bakesImage() && this.settings.mirror_flip !== false;
    this.photoEl.classList.toggle("is-mirrored", cssMirror);
  }

  /** هل الصورة النهائية مدموجة بالكامل في الملف (قلب + إطار + شريط العلامة)؟
   *  صحيح لوضعَي الكاميرا الحقيقية (webcam/gphoto2)؛ خطأ لوضع العيّنة (mock). */
  #bakesImage() {
    return this.cameraMode === "webcam" || this.cameraMode === "gphoto2";
  }

  /** يحمّل رابط صورة في عنصر Image ويعيده عند الجاهزية (أو يرمي عند الفشل). */
  #loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("image load failed: " + url));
      img.src = url;
    });
  }

  /** يضمن تحميل صورة الإطار (PNG) قبل الالتقاط — يتفادى التقاط بلا إطار
   *  إذا حدث الالتقاط فور تفعيل الإطار. يعيد الصورة أو null. */
  async #ensureOverlay() {
    if (this.overlayImg) return this.overlayImg;
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve((this.overlayImg = img));
      img.onerror = () => resolve((this.overlayImg = null));
      img.src = "/assets/overlay.png?t=" + Date.now();
    });
  }

  /** يضمن تحميل قفل العلامة الأفقي الجاهز (PNG واحد: الرمز + كلمة QAMRA محاذاة
   *  مسبقاً) قبل دمج الشريط السفلي. لا حاجة لتحميل الخط بعد الآن — الكلمة مخبوزة
   *  في الصورة. يعيد الصورة أو null. */
  async #ensureBrandMark() {
    if (this.brandMark) return this.brandMark;
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve((this.brandMark = img));
      img.onerror = () => resolve((this.brandMark = null));
      img.src = "/assets/brand/qamra-lockup-row.png";
    });
  }

  /** مراقبة دورية للحالة: تُقفل/تفتح الجهاز تلقائياً + شاشة التوقّف عند الخمول. */
  startPolling(ms = 5000) {
    const tick = async () => {
      const data = await this.refreshSession().catch(() => null);
      if (data) this.#applyLock(data);
      this.#tickScreensaver();
    };
    tick();
    setInterval(tick, ms);
  }

  /** تسجيل لمسة/تفاعل — يصفّر مؤقّت شاشة التوقّف. */
  noteActivity() {
    this.lastActivity = Date.now();
  }

  /** إغلاق شاشة التوقّف عند اللمس — العودة لشاشة الانتظار. */
  dismissScreensaver() {
    this.noteActivity();
    this.router.show("attract");
  }

  /** يُظهر شاشة التوقّف إن كانت مُفعّلة ومرّت مدّة الخمول على شاشة الانتظار. */
  #tickScreensaver() {
    if (!this.screensaverUrl) return; // ميزة اختيارية — لا صورة = معطّلة
    if (this.router.activeName !== "attract") return; // فقط من شاشة الانتظار
    if (Date.now() - this.lastActivity < SCREENSAVER_MS) return;
    if (this.screensaverImg.getAttribute("src") !== this.screensaverUrl) {
      this.screensaverImg.src = this.screensaverUrl;
    }
    this.router.show("screensaver");
  }

  /** حالة القفل من بيانات الحالة: paused | finished | null. */
  #lockState(data) {
    if (data.paused) return "paused";
    if (data.finished || data.time_over) return "finished";
    return null;
  }

  /**
   * يطبّق القفل — فقط على الشاشات الخاملة (لا يقاطع ضيفاً في منتصف التدفق).
   */
  #applyLock(data) {
    // شاشة التوقّف ضمن الخاملة حتى يتمكّن القفل من استبدالها، دون أن يعيدها القفل
    // المفتوح إلى الانتظار قسراً (تبقى حتى يلمسها الضيف).
    const idle = ["attract", "finished", "paused", "screensaver"];
    const active = this.router.activeName;
    if (!idle.includes(active)) return;

    const lock = this.#lockState(data);
    if (lock === "paused") {
      if (active !== "paused") this.router.show("paused");
    } else if (lock === "finished") {
      if (active !== "finished") this.router.show("finished");
    } else if (active === "paused" || active === "finished") {
      // فُكّ القفل على شاشة قفل → عودة لشاشة الانتظار
      this.router.show("attract");
    }
  }

  /** عرض خيارات مدة المؤقت (يُستدعى عند لمس شاشة الانتظار). */
  async showChooser() {
    this.#clearIdle();
    this.noteActivity();

    // حدّث الحالة أولاً (قد تكون تغيّرت من لوحة المشغّل)
    const data = (await this.refreshSession().catch(() => null)) || {};

    // إذا كان الجهاز مقفلاً (متوقّف/مكتمل/انتهى الوقت) لا نبدأ جلسة
    const lock = this.#lockState(data);
    if (lock === "paused") return this.router.show("paused");
    if (lock === "finished") return this.router.show("finished");

    // خيار واحد فقط؟ لا داعي لشاشة الاختيار — نبدأ المعاينة مباشرةً بتلك المدة.
    const opts = this.#timerOptions();
    if (opts.length <= 1) return this.run(opts[0] || DEFAULT_COUNTDOWN);

    this.#buildChooser();
    this.router.show("chooser");
    this.#armIdle();
  }

  /** مدد المؤقت المضبوطة من المشغّل، مُنقّاة إلى أرقام موجبة. */
  #timerOptions() {
    return (this.settings.timer_options || [DEFAULT_COUNTDOWN])
      .map(Number)
      .filter((n) => Number.isFinite(n) && n > 0);
  }

  #buildChooser() {
    const opts = this.#timerOptions();
    // الأرقام باللاتينية (إنجليزية) لتتطابق مع عدّاد الالتقاط.
    // البنية: عدسة دائرية بحلقات متّحدة المركز + الرقم في مركزها.
    this.optionsEl.innerHTML = opts
      .map(
        (n) =>
          `<button class="timer-opt" type="button" data-seconds="${n}">` +
          `<span class="timer-opt__core" aria-hidden="true"></span>` +
          `<span class="timer-opt__num">${n}</span></button>`
      )
      .join("");
  }

  async #showNotice(screen) {
    this.router.show(screen);
    await wait(3500);
    this.router.show("attract");
  }

  /** يقرأ حالة الجلسة والإعدادات من الخادم. */
  async refreshSession() {
    const { data } = await api.status();
    if (typeof data.remaining === "number") this.remaining = data.remaining;
    this.paused = !!data.paused;
    if (data.camera_mode) this.cameraMode = data.camera_mode;
    if (data.settings) this.applySettings(data.settings);
    return data;
  }

  /** بدء دورة التقاط جديدة بمدة مؤقت محددة (بالثواني). */
  async run(seconds = DEFAULT_COUNTDOWN) {
    if (this.busy) return;
    this.#clearIdle();
    this.noteActivity();

    if (this.remaining === 0) {
      await this.#showFinished();
      return;
    }

    this.busy = true;
    try {
      if (this.promptEl) this.promptEl.textContent = "انظر إلى المرآة";
      this.router.show("capture");

      // المعاينة الحيّة أثناء العدّ التنازلي: كاميرا المتصفح (webcam) أو
      // Live View من الكانون عبر بثّ MJPEG (gphoto2). في وضع العيّنة لا معاينة.
      await this.#startPreview();

      await wait(650);

      // زمن التقاط الكانون (gphoto2) ~1 ثانية حتى انطلاق الشاتر. فنطلق الالتقاط عند
      // بداية آخر ثانية من العدّاد ليتزامن الشاتر مع وصول العدّاد إلى الصفر، بدل أن
      // يبدأ بعده فيتأخر. الويبكام لحظيّ، فيبقى التقاطه عند الصفر كما هو.
      let capturePromise = null;
      await this.#runCountdown(seconds, () => {
        if (this.cameraMode === "gphoto2") {
          if (this.promptEl) this.promptEl.textContent = "ثبات…";
          capturePromise = this.#capture(); // التقاط مسبق يتزامن شاتره مع الصفر
        }
      });

      // كلمة "لحظة…" عند الصفر — إشارة لطيفة تموّه زمن النقل من الكانون.
      // نقطة ربط الفلاش العتادي مستقبلاً هنا، لحظة الالتقاط.
      if (this.promptEl) this.promptEl.textContent = "لحظة…";

      const data = await (capturePromise || this.#capture());
      this.#stopPreview();

      // فشل الالتقاط (الخادم ردّ بخطأ، أو بلا photo_url): لا نعرض صورة العيّنة كأنها
      // "صورتك"، ولا نترك الضيف عالقاً على شاشة الالتقاط — نعود لشاشة الانتظار.
      if (!data || data.ok === false || !data.photo_url) {
        this.router.show("attract");
        return;
      }

      // حدّث رصيد الباقة محلياً (العدّاد يُخصم مع كل التقاطة) حتى يُقفل عند النفاد
      if (typeof data.remaining === "number") this.remaining = data.remaining;

      await wait(450);
      await this.#showResult(data.photo_url);
      this.#armIdle();
    } catch (e) {
      // استثناء (رفض fetch أثناء العدّ/الالتقاط): لا نترك الكشك عالقاً — نعود للانتظار.
      console.error("[mirror] فشل دورة الالتقاط:", e);
      this.router.show("attract");
    } finally {
      this.busy = false;
      this.#stopPreview(); // ضمان إيقاف الكاميرا في كل الحالات
    }
  }

  /** يلتقط الصورة حسب مصدر الكاميرا، مع تراجع آمن إلى صورة العيّنة. */
  async #capture() {
    if (this.cameraMode === "webcam" && this.camera.ready) {
      try {
        // تأكّد من جاهزية الإطار قبل الدمج (يتفادى التقاط بلا إطار)
        const overlay = this.settings.overlay ? await this.#ensureOverlay() : null;
        // شريط اللوقو السفلي يُدمج في كل صورة (نتيجة/مشاركة/طباعة)
        const brandMark = await this.#ensureBrandMark();
        // دمج كل شيء في الصورة لحظة الالتقاط (قلب + إطار + شريط العلامة) لتكون نهائية
        const image = this.camera.capture({
          mirror: this.settings.mirror_flip !== false,
          overlay,
          brandMark,
        });
        const { ok, data } = await api.captureWebcam(image);
        if (ok) return data;
        console.error("[mirror] فشل رفع إطار الكاميرا:", data);
      } catch (e) {
        console.error("[mirror] تعذّر الالتقاط من كاميرا المتصفح:", e);
      }
    }

    if (this.cameraMode === "gphoto2") {
      const data = await this.#captureCanon();
      if (data) return data;
      // فشل الالتقاط من الكانون — نتراجع لمسار الخادم أدناه
    }

    // تراجع: مسار الخادم (عيّنة/عتاد)
    const { data } = await api.capture();
    return data;
  }

  /**
   * التقاط من الكانون (DSLR) ثم دمج العلامة في المتصفح:
   * الخادم يلتقط JPEG نظيفاً، نحمّله هنا، ندمج (قلب + إطار + شريط العلامة)
   * بنفس منطق الويبكام، ثم نرفع النهائية لتُحفظ وتُشارك/تُطبع بالعلامة.
   * يوقف بثّ المعاينة أولاً (لا يتداخل مع الالتقاط على نفس الاتصال).
   * يعيد بيانات الصورة النهائية، أو null عند الفشل (ليتراجع المنادي).
   */
  async #captureCanon() {
    this.#stopPreview(); // حرّر الاتصال قبل أمر الالتقاط
    try {
      const { ok, data } = await api.capture(); // التقاط الكانون الخام
      if (!ok || !data.photo_url) {
        console.error("[mirror] فشل التقاط الكانون:", data);
        return null;
      }
      const src = await this.#loadImage(data.photo_url);
      const overlay = this.settings.overlay ? await this.#ensureOverlay() : null;
      const brandMark = await this.#ensureBrandMark();
      // دقّة عالية لمسار الـDSLR (قصّ من مصدر 18MP بلا تكبير) — تحافظ على جودة
      // مناسبة للطباعة، بخلاف مقاس الويبكام الصغير. الشريط يتناسب تلقائياً.
      const image = this.camera.compositeFrom(src, {
        mirror: this.settings.mirror_flip !== false,
        overlay,
        brandMark,
        width: 2048,
        height: 3072,
        stripH: 256,
        quality: 0.95,
      });
      // recomposite: إعادة رفع لا تُحسب التقاطاً جديداً (الخصم تمّ في api.capture)
      const res = await api.captureWebcam(image, { recomposite: true });
      if (res.ok) {
        // رصيد الباقة يأتي من نداء الالتقاط (data)؛ نداء الدمج لا يعيده
        return { ...res.data, remaining: data.remaining };
      }
      console.error("[mirror] فشل رفع صورة الكانون المدموجة:", res.data);
      return data; // على الأقل أعِد الخام كي يرى الضيف صورته
    } catch (e) {
      console.error("[mirror] تعذّر الالتقاط/الدمج من الكانون:", e);
      return null;
    }
  }

  async #startPreview() {
    const mirror = this.settings.mirror_flip !== false;

    if (this.cameraMode === "gphoto2") {
      // Live View من الكانون كبثّ MJPEG يُعرض في عنصر <img> حيّ.
      // نطلب اتجاه اوتو-روتيت (من EXIF آخر التقاطة) لندوّر المعاينة فتطابق النتيجة،
      // لأن بثّ Live View نفسه لا يحمل EXIF ولا يستشعر الميلان.
      let deg = 0;
      try {
        const r = await api.cameraOrientation();
        if (r && r.ok) deg = r.rotate || 0;
      } catch (_) {
        /* نكمل بلا تدوير عند تعذّر الطلب */
      }
      this.previewImg.onerror = () => {
        console.warn("[mirror] تعذّر بثّ معاينة الكانون");
        this.previewImg.hidden = true;
      };
      this.#applyPreviewRotation(deg, mirror);
      this.previewImg.src = "/api/preview.mjpeg?t=" + Date.now();
      this.previewImg.hidden = false;
      return;
    }

    if (this.cameraMode === "webcam") {
      try {
        await this.camera.start();
        this.videoEl.hidden = false;
        this.videoEl.classList.toggle("is-mirrored", mirror);
      } catch (e) {
        // رفض الإذن أو سياق غير آمن (IP بدل localhost) — نكمل بصورة العيّنة
        console.warn("[mirror] تعذّر تشغيل كاميرا المتصفح:", e);
        this.videoEl.hidden = true;
      }
    }
    // وضع العيّنة (mock): لا معاينة حيّة
  }

  /**
   * يدوّر معاينة الكانون الحية ديناميكياً لتطابق اتجاه النتيجة (اوتو-روتيت).
   * deg: زاوية CSS (0/90/180/270) قادمة من EXIF آخر التقاطة. عند ربع دورة نُبادل
   * أبعاد الصندوق ليملأ الإطار الطولي؛ mirror: قلب أفقي في فضاء العرض.
   */
  #applyPreviewRotation(deg, mirror) {
    const img = this.previewImg;
    const s = img.style;
    // تصفير أي أنماط توجيه سابقة أولاً
    s.width = s.height = s.left = s.top = s.right = s.bottom = s.transformOrigin = "";
    const d = (((Number(deg) || 0) % 360) + 360) % 360;
    const m = mirror ? "scaleX(-1) " : "";
    if (d === 90 || d === 270) {
      const frame = img.parentElement; // .capture__frame (نسبة 2:3 طولية)
      const w = frame ? frame.clientWidth : 0;
      const h = frame ? frame.clientHeight : 0;
      if (w && h) {
        s.width = h + "px"; // أبعاد مُبادَلة ليملأ الإطار بعد ربع الدورة
        s.height = w + "px";
        s.left = "50%";
        s.top = "50%";
        s.right = "auto";
        s.bottom = "auto";
        s.transformOrigin = "center center";
      }
      s.transform = `translate(-50%, -50%) ${m}rotate(${d}deg)`;
    } else if (d === 180) {
      s.transform = `${m}rotate(180deg)`;
    } else {
      s.transform = mirror ? "scaleX(-1)" : "";
    }
  }

  #stopPreview() {
    // إيقاف بثّ معاينة الكانون (يغلق اتصال MJPEG) + كاميرا المتصفح معاً
    if (this.previewImg) {
      this.previewImg.hidden = true;
      this.previewImg.onerror = null;
      this.previewImg.removeAttribute("src");
      // إزالة أنماط التوجيه الداخلية حتى لا تبقى عالقة
      const s = this.previewImg.style;
      s.transform = s.width = s.height = s.left = s.top = s.right = s.bottom =
        s.transformOrigin = "";
    }
    this.videoEl.hidden = true;
    this.camera.stop();
  }

  async #onPrint() {
    if (this.busy) return;
    this.#clearIdle();
    this.noteActivity();
    this.busy = true;
    try {
      this.router.show("printing");
      const minShow = wait(1400);
      const { ok, data } = await api.print();
      await minShow;

      if (!ok) {
        this.remaining = 0;
        await this.#showFinished();
        return;
      }

      this.remaining = data.remaining;
      this.router.show("done");
      await wait(2600);

      if (this.remaining <= 0) {
        await this.#showFinished();
        return;
      }
      this.router.show("attract");
    } finally {
      this.busy = false;
    }
  }

  /** العودة إلى الشاشة الرئيسية (المس لتبدأ) — إنهاء وتجهيز للضيف التالي. */
  #onHome() {
    if (this.busy) return;
    this.#clearIdle();
    this.noteActivity();
    this.router.show("attract");
  }

  // --- أدوات داخلية ---
  async #runCountdown(from = DEFAULT_COUNTDOWN, onFinalBeat = null) {
    // تصميم مبسّط: رقم ضخم جداً في المركز يتناقص كل ثانية فوق المعاينة الحيّة.
    // onFinalBeat: يُستدعى عند بداية آخر ثانية (الرقم 1) — لإطلاق الالتقاط المسبق.
    const el = this.countdownEl;
    for (let n = from; n >= 1; n--) {
      el.textContent = String(n);
      // إعادة تشغيل حركة الظهور الناعم مع كل رقم
      el.classList.remove("is-tick");
      void el.offsetWidth; // إعادة تدفّق لإعادة بدء الأنيميشن
      el.classList.add("is-tick");
      if (n === 1 && onFinalBeat) onFinalBeat();
      await wait(1000);
    }
    el.textContent = "";
    el.classList.remove("is-tick");
  }

  // يعرض شاشة الاكتمال ويبقى عليها (قفل) حتى يبدأ المشغّل مناسبة جديدة.
  // فتح القفل يتم عبر المراقبة الدورية (startPolling) عند تغيّر الحالة.
  #showFinished() {
    this.#clearIdle();
    this.router.show("finished");
  }

  #showResult(url) {
    // الإطار/الشعار فوق الصورة — في وضعَي الكاميرا الحقيقية (webcam/gphoto2) يكون
    // مدموجاً في الصورة المخزّنة أصلاً، فلا نعرضه كطبقة إضافية حتى لا يتكرّر.
    if (this.settings.overlay && !this.#bakesImage()) {
      this.overlayEl.src = "/assets/overlay.png?t=" + Date.now();
      this.overlayEl.hidden = false;
    } else {
      this.overlayEl.hidden = true;
    }

    return new Promise((resolve) => {
      const img = this.photoEl;
      const done = () => {
        this.router.show("result");
        resolve();
      };
      if (img.src.endsWith(url)) return done();
      img.onload = done;
      img.onerror = done;
      img.src = url;
    });
  }

  #armIdle() {
    this.#clearIdle();
    this.idleTimer = setTimeout(() => {
      this.router.show("attract");
    }, IDLE_MS);
  }

  #clearIdle() {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }
}
