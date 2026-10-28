// لوحة المشغّل: بوابة رمز + حالة مباشرة + إعدادات + تحكّم الجلسة.
// (ملف مستقل عن تطبيق الضيف — بلا وحدات ES لتبسيط التحميل.)

(function () {
  "use strict";

  var PIN_KEY = "mirror_admin_pin";
  var pin = null;
  var formFilled = false;
  var refreshTimer = null;

  var $ = function (id) { return document.getElementById(id); };
  var AR = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];
  function toAr(n) { return String(n).replace(/\d/g, function (d) { return AR[d]; }); }
  function fmtTime(sec) {
    var m = Math.floor(sec / 60), h = Math.floor(m / 60);
    return h > 0 ? h + "س " + (m % 60) + "د" : m + "د";
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {});
    if (opts.json !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    if (pin) opts.headers["X-Admin-Pin"] = pin;
    return fetch(path, opts);
  }

  function flash(el, msg, ok) {
    el.textContent = msg;
    el.style.color = ok === false ? "var(--error)" : "var(--ok)";
    setTimeout(function () { el.textContent = ""; }, 2500);
  }

  // --- بوابة الرمز ---
  function tryLogin(candidate) {
    return fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: candidate }),
    }).then(function (r) { return r.ok; });
  }

  function showDash() {
    $("gate").classList.add("hidden");
    $("dash").classList.remove("hidden");
    refresh();
    if (!refreshTimer) refreshTimer = setInterval(refresh, 3000);
  }

  // إنهاء جلسة المشغّل: يمسح الرمز ويعيد البوابة — مهمّ على متصفّح مشترك.
  function logout() {
    pin = null;
    try { sessionStorage.removeItem(PIN_KEY); } catch (e) {}
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    formFilled = false;
    $("dash").classList.add("hidden");
    $("gate").classList.remove("hidden");
    $("pin").value = "";
  }

  function onLogin() {
    var candidate = $("pin").value.trim();
    $("pin-err").textContent = "";
    tryLogin(candidate).then(function (ok) {
      if (ok) {
        pin = candidate;
        // جلسة المشغّل فقط: sessionStorage يبقى عبر إعادة التحميل لكنه يُمسح بإغلاق
        // التبويب — فلا يبقى الرمز على متصفّح مشترك (بخلاف localStorage الدائم).
        try { sessionStorage.setItem(PIN_KEY, pin); } catch (e) {}
        showDash();
      } else {
        $("pin-err").textContent = "رمز غير صحيح";
        $("pin").value = "";
      }
    });
  }

  // --- الحالة المباشرة ---
  function refresh() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (d) {
      $("v-remaining").textContent = toAr(d.remaining);
      $("v-limit").textContent = toAr(d.limit);
      $("v-used").textContent = toAr(d.used);
      $("v-time").textContent = fmtTime(d.remaining_seconds);
      $("banner-finished").classList.toggle("show", !!d.finished && !d.paused);
      $("banner-time").classList.toggle("show", !!d.time_over);
      $("banner-paused").classList.toggle("show", !!d.paused);
      $("btn-pause").textContent = d.paused ? "استئناف" : "إيقاف مؤقت";
      $("btn-pause").dataset.paused = d.paused ? "1" : "0";
      if (!formFilled && d.settings) { fillForm(d.settings); formFilled = true; }
    }).catch(function () {});
  }

  function fillForm(s) {
    $("s-timers").value = (s.timer_options || [5, 10, 15]).join(", ");
    $("s-mirror").checked = s.mirror_flip !== false;
    $("s-flash").checked = s.flash_enabled !== false;
    $("s-print").checked = s.print_enabled !== false;
    $("s-copies").value = s.copies || 1;
    $("overlay-state").textContent = s.overlay ? "إطار مرفوع ✓" : "لا يوجد إطار";
    $("saver-state").textContent = s.screensaver ? "صورة مرفوعة ✓" : "لا يوجد (معطّلة)";
  }

  // --- حفظ الإعدادات ---
  function onSave() {
    var timers = $("s-timers").value.split(",")
      .map(function (x) { return parseInt(x.trim(), 10); })
      .filter(function (x) { return x > 0; });
    var body = {
      timer_options: timers.length ? timers : [5, 10, 15],
      mirror_flip: $("s-mirror").checked,
      flash_enabled: $("s-flash").checked,
      print_enabled: $("s-print").checked,
      copies: Math.min(5, Math.max(1, parseInt($("s-copies").value, 10) || 1)),
    };
    api("/api/settings", { method: "PUT", json: body }).then(function (r) {
      flash($("saved-msg"), r.ok ? "تم الحفظ ✓" : "تعذّر الحفظ", r.ok);
    });
  }

  // --- تحكّم الجلسة ---
  function onReset() {
    if (!confirm("بدء مناسبة جديدة؟ سيُصفّر العدّاد.")) return;
    api("/api/session/reset", { method: "POST", json: {
      photo_limit: parseInt($("f-photos").value, 10) || 100,
      session_minutes: parseInt($("f-minutes").value, 10) || 180,
    }}).then(refresh);
  }
  function onExtend() {
    api("/api/session/extend", { method: "POST", json: {
      add_photos: parseInt($("ex-photos").value, 10) || 0,
      add_minutes: parseInt($("ex-minutes").value, 10) || 0,
    }}).then(refresh);
  }
  function onPause() {
    var paused = $("btn-pause").dataset.paused === "1";
    api("/api/session/pause", { method: "POST", json: { paused: !paused } }).then(refresh);
  }
  function onEnd() {
    if (!confirm("إنهاء الجلسة الآن؟")) return;
    api("/api/session/end", { method: "POST", json: {} }).then(refresh);
  }

  // --- الإطار ---
  function onOverlayUp() {
    var f = $("overlay-file").files[0];
    if (!f) { flash($("overlay-state"), "اختر ملف PNG أولاً", false); return; }
    var fd = new FormData();
    fd.append("overlay", f);
    api("/api/admin/overlay", { method: "POST", body: fd }).then(function (r) {
      flash($("overlay-state"), r.ok ? "تم رفع الإطار ✓" : "فشل الرفع (PNG فقط)", r.ok);
    });
  }
  function onOverlayRm() {
    api("/api/admin/overlay", { method: "DELETE" }).then(function () {
      flash($("overlay-state"), "أُزيل الإطار", true);
    });
  }

  // --- شاشة التوقّف (ثيم المناسبة) ---
  function onSaverUp() {
    var f = $("saver-file").files[0];
    if (!f) { flash($("saver-state"), "اختر صورة أولاً", false); return; }
    var fd = new FormData();
    fd.append("image", f);
    api("/api/admin/screensaver", { method: "POST", body: fd }).then(function (r) {
      flash($("saver-state"), r.ok ? "تم رفع صورة شاشة التوقّف ✓" : "فشل الرفع (PNG/JPG/WEBP فقط)", r.ok);
    });
  }
  function onSaverRm() {
    api("/api/admin/screensaver", { method: "DELETE" }).then(function () {
      flash($("saver-state"), "أُلغيت شاشة التوقّف", true);
    });
  }

  // --- تحكّم الجهاز ---
  function onReboot() {
    if (!confirm("إعادة تشغيل جهاز البوث الآن؟")) return;
    api("/api/system/reboot", { method: "POST", json: {} }).then(function (r) {
      flash($("system-msg"), r.ok ? "جارٍ إعادة التشغيل…" : "تعذّر التنفيذ", r.ok);
    }).catch(function () { flash($("system-msg"), "جارٍ إعادة التشغيل…", true); });
  }
  function onPoweroff() {
    if (!confirm("إطفاء جهاز البوث الآن؟ لن يعمل حتى تشغّله يدوياً من الزر.")) return;
    api("/api/system/poweroff", { method: "POST", json: {} }).then(function (r) {
      flash($("system-msg"), r.ok ? "جارٍ الإطفاء…" : "تعذّر التنفيذ", r.ok);
    }).catch(function () { flash($("system-msg"), "جارٍ الإطفاء…", true); });
  }

  // --- تغيير الرمز ---
  function onPinChange() {
    var np = $("s-newpin").value.trim();
    api("/api/admin/pin", { method: "POST", json: { new_pin: np } }).then(function (r) {
      if (r.ok) {
        pin = np;
        try { sessionStorage.setItem(PIN_KEY, pin); } catch (e) {}
        $("s-newpin").value = "";
        flash($("pin-msg"), "تم تغيير الرمز ✓", true);
      } else {
        flash($("pin-msg"), "الرمز قصير جداً (٤ على الأقل)", false);
      }
    });
  }

  function init() {
    $("login").addEventListener("click", onLogin);
    $("pin").addEventListener("keydown", function (e) { if (e.key === "Enter") onLogin(); });
    $("btn-save").addEventListener("click", onSave);
    $("btn-reset").addEventListener("click", onReset);
    $("btn-extend").addEventListener("click", onExtend);
    $("btn-pause").addEventListener("click", onPause);
    $("btn-end").addEventListener("click", onEnd);
    $("btn-overlay-up").addEventListener("click", onOverlayUp);
    $("btn-overlay-rm").addEventListener("click", onOverlayRm);
    $("btn-saver-up").addEventListener("click", onSaverUp);
    $("btn-saver-rm").addEventListener("click", onSaverRm);
    $("btn-pin").addEventListener("click", onPinChange);
    $("btn-reboot").addEventListener("click", onReboot);
    $("btn-poweroff").addEventListener("click", onPoweroff);
    $("btn-logout").addEventListener("click", logout);

    // تنظيف الرمز القديم الدائم من الأجهزة التي سجّلت قبل هذا التغيير.
    try { localStorage.removeItem(PIN_KEY); } catch (e) {}

    // استعادة جلسة التبويب الحالية فقط (sessionStorage) — لا يبقى بعد إغلاق التبويب.
    var saved = null;
    try { saved = sessionStorage.getItem(PIN_KEY); } catch (e) {}
    if (saved) tryLogin(saved).then(function (ok) {
      if (ok) { pin = saved; showDash(); }
      else { try { sessionStorage.removeItem(PIN_KEY); } catch (e) {} }
    });
  }

  init();
})();
