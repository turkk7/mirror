// كاميرا المتصفح (getUserMedia) — مصدر التقاط للاختبار على الماك/أي جهاز.
//
// ملاحظة أمان: getUserMedia يعمل فقط في سياق آمن:
// http://localhost (أو https). لا يعمل عبر عنوان IP على الشبكة بدون https.

export class Camera {
  // أبعاد منطقة الصورة (بورتريه 2:3) + ارتفاع الشريط السفلي للعلامة
  static OUT_W = 1200;
  static OUT_H = 1800;
  static STRIP_H = 150; // الشريط الكريمي السفلي الذي يحمل اللوقو
  // ارتفاع قفل العلامة داخل الشريط (نسبةً لارتفاع الشريط). صغير بما يكفي ليبقى
  // له هامش علوي/سفلي مريح فلا يلمسه قصّ الطباعة بلا حواف.
  static LOGO_H_FRAC = 0.52;
  // الطباعة بلا حواف تُكبّر الصورة قليلاً وتقصّ أطرافها؛ الحافة السفلى (أسفل
  // الشريط) هي الأكثر عرضةً. نحجز هذا الكسر من *ارتفاع الصورة* عند أسفل الشريط
  // كمنطقة آمنة ونوسّط القفل داخل ما تبقّى — بديلٌ مبدئيّ عن الإزاحات التقديرية.
  // 0 يعيد التوسيط الهندسي التام (مناسب لطابعة ذات حواف أو نسخة رقمية فقط).
  static PRINT_BLEED = 0.02;

  constructor() {
    this.video = document.getElementById("cam-video");
    this.canvas = document.getElementById("cam-canvas");
    this.stream = null;
  }

  get ready() {
    return !!this.stream && this.video.readyState >= 2; // HAVE_CURRENT_DATA
  }

  /** يشغّل الكاميرا ويعرض المعاينة الحيّة. يرمي استثناءً عند الرفض/التعذّر. */
  async start() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    // انتظار توفّر أبعاد الفيديو الفعلية قبل السماح بالالتقاط
    if (!this.video.videoWidth) {
      await new Promise((resolve) => {
        this.video.addEventListener("loadedmetadata", resolve, { once: true });
      });
    }
  }

  /**
   * يلتقط إطاراً نهائياً موحّداً ويعيده كـ data URL:
   * - mirror: قلب أفقي (كما يراه الضيف في المعاينة).
   * - overlay: صورة إطار/شعار تُدمج فوق منطقة الصورة (تُمدّد لتملأها).
   * - brandMark: صورة قفل العلامة الأفقي الجاهز (الرمز + كلمة QAMRA كصورة
   *   واحدة محاذاة مسبقاً)؛ عند تمريرها يُرسم شريط كريمي سفلي يحمل اللوقو
   *   موسّطاً — فيظهر في النتيجة والمشاركة والطباعة.
   * الخرج النهائي ثابت بنسبة 2:3 بالضبط (width×height)؛ الشريط يُرسم *داخل*
   * هذا الإطار في أسفله (لا مضافاً تحته)، فتطابق الطباعة ورق 10×15 بلا حواف
   * دون قصّ الشريط. منطقة الصورة = الإطار ناقص ارتفاع الشريط.
   */
  capture(opts = {}) {
    const v = this.video;
    return this.composite(v, v.videoWidth || 1280, v.videoHeight || 720, opts);
  }

  /**
   * نفس منطق capture لكن من صورة جاهزة (HTMLImageElement) — تُستخدم لصورة
   * الكانون (DSLR) القادمة من gphoto2 لتُدمج بنفس الإطار والشريط والقصّ.
   */
  compositeFrom(img, opts = {}) {
    const sw = img.naturalWidth || img.width || Camera.OUT_W;
    const sh = img.naturalHeight || img.height || Camera.OUT_H;
    return this.composite(img, sw, sh, opts);
  }

  /**
   * يدمج مصدراً (فيديو/صورة) في الصورة النهائية الموحّدة ويعيده كـ data URL.
   * source: عنصر يُرسم عبر drawImage؛ sw/sh أبعاده الأصلية.
   * الخيارات: mirror (قلب أفقي)، overlay (إطار/شعار)، brandMark (شريط اللوقو السفلي).
   */
  composite(
    source,
    sw,
    sh,
    {
      mirror = false,
      overlay = null,
      brandMark = null,
      width = Camera.OUT_W,
      height = Camera.OUT_H,
      stripH = Camera.STRIP_H,
      printBleed = Camera.PRINT_BLEED,
      quality = 0.92,
    } = {}
  ) {
    const c = this.canvas;
    const strip = brandMark ? stripH : 0;
    // الإجمالي يبقى width×height (2:3 بالضبط) ليطابق ورق 10×15 بلا حواف؛
    // الشريط يُرسم داخل هذا الإطار في أسفله، ومنطقة الصورة فوقه.
    c.width = width;
    c.height = height;
    const ctx = c.getContext("2d");

    // ارتفاع منطقة الصورة = الإطار الكامل ناقص الشريط (الشريط داخل 2:3)
    const photoH = height - strip;

    // قصّ "cover" داخل منطقة الصورة فقط (فوق الشريط)
    const scale = Math.max(width / sw, photoH / sh);
    const dw = sw * scale;
    const dh = sh * scale;
    const dx = (width - dw) / 2;
    const dy = (photoH - dh) / 2;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, width, photoH);
    ctx.clip();
    if (mirror) {
      ctx.translate(width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(source, dx, dy, dw, dh);
    ctx.restore();

    if (overlay) ctx.drawImage(overlay, 0, 0, width, photoH);
    if (brandMark)
      this.#drawBrandStrip(ctx, width, height, photoH, stripH, brandMark, printBleed);

    return c.toDataURL("image/jpeg", quality);
  }

  /**
   * يرسم الشريط الكريمي السفلي مع قفل العلامة الأفقي الجاهز (صورة واحدة محاذاة
   * مسبقاً: الرمز + كلمة QAMRA). رسم صورة واحدة بدل تركيب رمز + نصّ حيّ يلغي
   * اعتماد النتيجة على تحميل الخط ومقاييس الكانفس، وهو مصدر العيوب السابقة
   * (كلمة بخطّ احتياطي، أو خطّ أساس مختلف عن الرمز فيبدو القفل مائلاً).
   *
   * التوسيط: أفقياً توسيط هندسي تام (لا إزاحة تقديرية) فيبدو في المنتصف على
   * النسخة الرقمية وعلى طبعة سليمة التسجيل. رأسياً نوسّط داخل منطقة آمنة تُستبعد
   * منها حافة القصّ السفلية للطباعة بلا حواف (printBleed)، فيبقى القفل موسّطاً
   * بصرياً ضمن الشريط الظاهر بعد الطباعة دون أن يلمسه القصّ.
   */
  #drawBrandStrip(ctx, width, height, photoH, stripH, lockImg, printBleed) {
    // خلفية الشريط الكريمية (تدرّج رأسي ناعم)
    const g = ctx.createLinearGradient(0, photoH, 0, photoH + stripH);
    g.addColorStop(0, "#faf7f1");
    g.addColorStop(1, "#eee7db");
    ctx.fillStyle = g;
    ctx.fillRect(0, photoH, width, stripH);

    // أبعاد القفل من نسبة الصورة الجاهزة (ارتفاع ثابت نسبةً للشريط)
    const ratio =
      lockImg.naturalWidth && lockImg.naturalHeight
        ? lockImg.naturalWidth / lockImg.naturalHeight
        : 1;
    const logoH = Math.round(stripH * Camera.LOGO_H_FRAC);
    const logoW = Math.round(logoH * ratio);

    // أفقياً: توسيط هندسي تام
    const logoX = Math.round((width - logoW) / 2);

    // رأسياً: نحجز حافة القصّ السفلية (بكسلات) ونوسّط القفل في ما تبقّى من الشريط
    const bleedPx = Math.round(height * printBleed);
    const safeTop = photoH; // أعلى الشريط (الحافة العلوية غير معرّضة للقصّ)
    const safeBottom = photoH + stripH - bleedPx; // أسفل المنطقة الآمنة
    const logoY = Math.round((safeTop + safeBottom - logoH) / 2);

    ctx.drawImage(lockImg, logoX, logoY, logoW, logoH);
  }

  /** يوقف الكاميرا ويحرّر الضوء/الجهاز. */
  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    this.video.srcObject = null;
  }
}
