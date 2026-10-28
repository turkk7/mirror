"""مرآة الفوتوبوث — خادم Flask.

يقدّم الواجهة ويعرض واجهة برمجية (API) للتحكم بالكاميرا والطباعة.
في هذه الخطوة (الأساس) المسارات عبارة عن هياكل (stubs) ترجع استجابات محاكاة،
وسنربطها بالعتاد الحقيقي في الخطوتين ٥ و٦.
"""

import base64
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import uuid

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from config import (
    Config,
    CAPTURES_DIR,
    CERT_PATH,
    FRONTEND_DIR,
    KEY_PATH,
    OVERLAY_PATH,
    SETTINGS_PATH,
)
from camera import CameraError, Gphoto2Camera
from photos import PhotoStore
from qr import make_qr_svg
from session import Session
from settings_store import SettingsStore
from touch import TouchReader


def get_lan_ip() -> str:
    """عنوان IP للجهاز على الشبكة المحلية (لروابط المشاركة على جوالات الضيوف)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def get_public_host() -> str:
    """العنوان المستخدم في روابط المشاركة: عنوان ثابت (mirror.local) إن ضُبط،
    وإلا عنوان IP الحالي. هكذا لا يتغيّر رابط التاق عند تبدّل IP من الراوتر."""
    return Config.PUBLIC_HOST or get_lan_ip()


def share_base() -> str:
    """عنوان الأساس لروابط المشاركة (QR/صفحة الصورة).

    إن ضُبط ``MIRROR_PUBLIC_BASE`` (مثل Tailscale Funnel) نستخدمه كما هو — رابط
    عام https بلا منفذ يعمل من أي جوال على الإنترنت. وإلا نرجع للعنوان المحلي
    ``http://<ip>:<port>`` (يتطلّب أن يكون الضيف على نفس الشبكة)."""
    if Config.PUBLIC_BASE:
        return Config.PUBLIC_BASE.rstrip("/")
    return f"{request.scheme}://{get_public_host()}:{Config.PORT}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("mirror")


def schedule_system_power(action: str) -> bool:
    """تنفيذ أمر نظام (poweroff/reboot) بعد تأخير قصير حتى تصل استجابة HTTP أولاً.

    يعمل على جهاز البوث (لينكس/systemd). إن كان الخادم لا يعمل بصلاحية الجذر
    يُسبَق الأمر بـ sudo -n (يتطلّب قاعدة NOPASSWD لـ systemctl على البوث).
    في بيئة التطوير (لا يوجد systemctl) يُتجاهل الأمر بأمان.
    """
    systemctl = shutil.which("systemctl")
    if not systemctl:
        log.warning("systemctl غير متوفّر — تجاهل أمر %s (بيئة تطوير؟)", action)
        return False
    cmd = [systemctl, action]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd

    def run():
        try:
            subprocess.Popen(cmd, start_new_session=True)
        except Exception as exc:  # noqa: BLE001
            log.error("فشل تنفيذ أمر %s: %s", action, exc)

    threading.Timer(1.0, run).start()
    return True


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    # حدّ حجم الطلب (إطار كاميرا المتصفح عادةً < بضعة ميغابايت)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    # حالة الجلسة (عدد الصور / الحدّ)
    session = Session(
        photo_limit=app.config["SESSION_PHOTO_LIMIT"],
        duration_minutes=app.config["SESSION_DURATION_MINUTES"],
    )
    photos = PhotoStore(ttl=app.config["LATEST_TTL"], captures_dir=CAPTURES_DIR)
    settings = SettingsStore(SETTINGS_PATH, default_pin=app.config["ADMIN_PIN"])

    # كاميرا DSLR (gphoto2) — تُهيّأ فقط في وضع gphoto2 الحقيقي (ليس المحاكاة).
    # في بقية الأوضاع تبقى None ولا يُستدعى أي أمر gphoto2.
    camera = None
    if app.config["CAMERA_MODE"] == "gphoto2" and not app.config["MOCK_HARDWARE"]:
        camera = Gphoto2Camera(
            bin_path=app.config["GPHOTO2_BIN"],
            capture_timeout=app.config["CAPTURE_TIMEOUT"],
            state_path=SETTINGS_PATH.parent / "camera_orientation",
        )
        log.info("تهيئة كاميرا gphoto2 (الكانون)")

    # جسر طبقة اللمس (حسّاس ToF): يقرأ المنفذ التسلسلي ويبثّه بـSSE للواجهة.
    # يُفعّل عبر MIRROR_TOUCH=1 (على البوث)؛ آمن الإنشاء — يتجاهل غياب المنفذ/pyserial.
    touch = None
    if app.config["TOUCH_ENABLED"]:
        touch = TouchReader(port=app.config["TOUCH_PORT"])
        touch.start()
        log.info("تهيئة جسر طبقة اللمس (ToF عبر SSE)")

    # معايرة طبقة اللمس — تُخزَّن على الخادم وتجلبها الواجهة كل ثوانٍ، فيُضبط من البوث
    # عبر POST /api/touch/cal بلا إعادة تحميل الكيوسك. dTop/dBottom بالمليمتر (أعلى/أسفل
    # الشاشة)، minMm/maxMm = بوابة قبول القراءة.
    TOUCH_CAL_PATH = SETTINGS_PATH.parent / "touch_cal.json"
    # points = نقاط المعايرة [{d: مسافة‌مم, ny: موضع‌رأسي 0..1}] مرتّبة؛ المصدر الموثوق
    # لخريطة المسافة→الموضع (خطّية بالقطع). dTop/dBottom = خريطة نقطتين احتياطية.
    # calibrate = علم يأمر الكيوسك ببدء روتين المعايرة التفاعلي.
    TOUCH_CAL_DEFAULT = {
        "points": [], "dTop": 470, "dBottom": 85,
        # maxMm يجب أن يتجاوز القمّة (~١٣٨٥مم في الشاشة الطولية، وضع Long) وإلا رُفضت
        # نقطة المعايرة العليا؛ ويبقى دون خلفية المشهد الفارغ ~٢٧٠٠مم. (قيمة البوث.)
        "minMm": 80, "maxMm": 1500, "calibrate": False,
        # هامش منع النقر المزدوج: إطارات الضغط/التحرّر + تهدئة بعد النقرة (مل‌ث).
        "pressFrames": 3, "releaseFrames": 8, "cooldownMs": 450,
        # رقم إصدار: رفعه يأمر الكيوسك بإعادة تحميل نفسه (لتفعيل JS جديد بلا إقلاع).
        "rev": 0,
    }

    def _load_touch_cal() -> dict:
        out = dict(TOUCH_CAL_DEFAULT)
        try:
            data = json.loads(TOUCH_CAL_PATH.read_text(encoding="utf-8"))
            for k in ("dTop", "dBottom", "minMm", "maxMm", "pressFrames", "releaseFrames", "cooldownMs", "rev"):
                if isinstance(data.get(k), (int, float)):
                    out[k] = data[k]
            if isinstance(data.get("calibrate"), bool):
                out["calibrate"] = data["calibrate"]
            if isinstance(data.get("points"), list):
                out["points"] = [
                    {"d": float(p["d"]), "ny": float(p["ny"])}
                    for p in data["points"]
                    if isinstance(p, dict)
                    and isinstance(p.get("d"), (int, float))
                    and isinstance(p.get("ny"), (int, float))
                ]
        except Exception:  # noqa: BLE001 — ملف مفقود/تالف = الافتراضي
            pass
        return out

    def _save_touch_cal(cal: dict) -> None:
        TOUCH_CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOUCH_CAL_PATH.write_text(json.dumps(cal), encoding="utf-8")

    def _publish_cloud(raw: bytes, ext: str) -> None:
        """يرفع الصورة لخدمة المشاركة العامة (VPS) في خيط منفصل.

        معطّل ما لم يُضبط العنوان والمفتاح؛ لا يعطّل الالتقاط؛ وفشل الشبكة
        (أو توقّف الخادم) يُسجَّل تحذيراً فقط ولا يؤثّر على البوث.
        """
        url = app.config.get("CLOUD_UPLOAD_URL", "")
        key = app.config.get("CLOUD_UPLOAD_KEY", "")
        if not url or not key:
            return
        ctype = "image/png" if ext == "png" else "image/jpeg"
        timeout = app.config.get("CLOUD_UPLOAD_TIMEOUT", 20)

        def _do() -> None:
            try:
                req = urllib.request.Request(
                    url, data=raw, method="POST",
                    headers={"X-Upload-Key": key, "Content-Type": ctype},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp.read()
                log.info("رُفعت الصورة لخدمة المشاركة العامة")
            except Exception as exc:  # الشبكة لا تُسقط الالتقاط
                log.warning("تعذّر رفع الصورة للسحابة: %s", exc)

        threading.Thread(target=_do, daemon=True).start()

    def _store_photo(raw: bytes, ext: str) -> dict:
        """يحفظ بايتات صورة على القرص ويسجّلها في المخزن، ويعيد استجابة موحّدة.

        منطق مشترك بين التقاط الكانون (gphoto2) والتقاط كاميرا المتصفح (webcam)
        ليعمل الاثنان مع المشاركة/QR/NFC بنفس الطريقة.
        """
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex[:12]}.{ext}"
        (CAPTURES_DIR / fname).write_bytes(raw)
        photo_url = f"/captures/{fname}"
        photo_id = photos.add(photo_url)
        _publish_cloud(raw, ext)  # يرفعها للسحابة ليأخذها الضيف عبر إنترنته
        share_url = f"{share_base()}/p/{photo_id}"
        return dict(ok=True, photo_url=photo_url, photo_id=photo_id, share_url=share_url)

    # ------------------------------------------------------------------ #
    # الواجهة (Frontend)
    # ------------------------------------------------------------------ #
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/admin")
    def admin():
        return send_from_directory(FRONTEND_DIR, "admin.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(FRONTEND_DIR, filename)

    # ------------------------------------------------------------------ #
    # واجهة برمجية (API)
    # ------------------------------------------------------------------ #
    @app.get("/api/status")
    def status():
        """حالة النظام + الجلسة + الإعدادات — يستخدمها الواجهة."""
        return jsonify(
            ok=True,
            mock=app.config["MOCK_HARDWARE"],
            camera_mode=app.config["CAMERA_MODE"],
            live_preview=camera is not None,  # هل تتوفّر معاينة Live View (المسار أ)
            settings=settings.public(),
            **session.snapshot(),
        )

    @app.post("/api/capture")
    def capture():
        """التقاط صورة من الكاميرا الرئيسية.

        - وضع المحاكاة: يرجع صورة عيّنة ثابتة.
        - وضع gphoto2: يلتقط من الكانون (DSLR) عبر gphoto2 ويحفظها.
        """
        log.info("طلب التقاط صورة (محاكاة=%s، مصدر=%s)",
                 app.config["MOCK_HARDWARE"], app.config["CAMERA_MODE"])

        # لا نلتقط إذا اكتملت الباقة أو الجهاز متوقّف (الخصم لكل التقاطة)
        snap = session.snapshot()
        if snap["finished"] or snap["paused"]:
            return jsonify(
                ok=False, error="unavailable",
                reason="finished" if snap["finished"] else "paused",
                remaining=snap["remaining"],
            ), 409

        if app.config["MOCK_HARDWARE"]:
            photo_url = "/assets/sample.svg"
            photo_id = photos.add(photo_url)
            share_url = f"{share_base()}/p/{photo_id}"
            st = session.consume_capture()
            return jsonify(
                ok=True, photo_url=photo_url, photo_id=photo_id,
                share_url=share_url, remaining=st["remaining"],
            )

        if camera is not None:
            try:
                raw = camera.capture()
            except CameraError as exc:
                log.error("فشل التقاط الكانون: %s", exc)
                return jsonify(ok=False, error="capture_failed", detail=str(exc)), 503
            resp = _store_photo(raw, "jpg")
            st = session.consume_capture()  # خصم من الباقة بعد نجاح الالتقاط فقط
            resp["remaining"] = st["remaining"]
            log.info("التقاط من الكانون: %s (%d بايت) — المتبقي %s",
                     resp["photo_url"], len(raw), st["remaining"])
            return jsonify(resp)

        # لا كاميرا DSLR مهيّأة (مثلاً وضع webcam يلتقط عبر /api/capture/webcam)
        return jsonify(ok=False, error="camera not connected"), 503

    @app.post("/api/capture/webcam")
    def capture_webcam():
        """التقاط من كاميرا المتصفح (getUserMedia).

        تستقبل إطاراً مُرمّزاً (data URL) من الواجهة، تحفظه على القرص،
        وتسجّله في مخزن الصور ليعمل مع المشاركة/QR/NFC كأي صورة.
        """
        data = request.get_json(silent=True) or {}
        image = data.get("image", "")
        # إعادة رفع صورة الكانون بعد دمج العلامة في المتصفح — لا تُحسب التقاطاً
        # جديداً (الخصم تمّ في /api/capture)، وتُحفظ دائماً لتظهر النتيجة النهائية.
        recomposite = bool(data.get("recomposite"))
        if not isinstance(image, str) or not image.startswith("data:image/"):
            return jsonify(ok=False, error="missing image"), 400
        try:
            header, b64 = image.split(",", 1)
            raw = base64.b64decode(b64)
        except (ValueError, base64.binascii.Error):
            return jsonify(ok=False, error="bad image"), 400

        if not recomposite:
            snap = session.snapshot()
            if snap["finished"] or snap["paused"]:
                return jsonify(
                    ok=False, error="unavailable",
                    reason="finished" if snap["finished"] else "paused",
                    remaining=snap["remaining"],
                ), 409

        ext = "png" if "image/png" in header else "jpg"
        resp = _store_photo(raw, ext)
        if not recomposite:
            st = session.consume_capture()  # خصم التقاطة الويبكام
            resp["remaining"] = st["remaining"]
        log.info("التقاط من كاميرا المتصفح: %s (%d بايت)%s",
                 resp["photo_url"], len(raw), " [دمج]" if recomposite else "")
        return jsonify(resp)

    @app.get("/captures/<path:filename>")
    def serve_capture(filename: str):
        """تقديم الصور الملتقطة (تُعرض في صفحة النتيجة وصفحة المشاركة)."""
        return send_from_directory(CAPTURES_DIR, filename)

    @app.get("/api/preview.mjpeg")
    def preview_mjpeg():
        """بثّ Live View من الكانون كـ MJPEG (المسار أ — معاينة على الشاشة).

        تُستهلك من الواجهة عبر ``<img src="/api/preview.mjpeg">``. يتوقّف البثّ
        تلقائياً أثناء الالتقاط (القفل في camera.py)، فتعيد الواجهة الطلب بعده.
        متاح فقط في وضع gphoto2 الحقيقي.
        """
        if camera is None:
            return jsonify(ok=False, error="preview_unavailable"), 503
        try:
            frames = camera.preview_stream()
        except CameraError as exc:
            log.error("تعذّر بدء المعاينة: %s", exc)
            return jsonify(ok=False, error="preview_failed", detail=str(exc)), 503

        boundary = "qamraframe"

        def multipart():
            try:
                for jpeg in frames:
                    yield (
                        b"--" + boundary.encode() + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg + b"\r\n"
                    )
            except CameraError as exc:
                log.error("انقطاع بثّ المعاينة: %s", exc)

        return Response(
            multipart(),
            mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
            headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
        )

    @app.get("/api/touch/stream")
    def touch_stream():
        """بثّ إطارات حسّاس اللمس الخام (R,d,v / S,..) كـServer-Sent Events.

        تستهلكها الواجهة عبر EventSource وتملك هي المعايرة وكشف اللمسة وحقن النقرة.
        متاح فقط حين تفعيل جسر اللمس (MIRROR_TOUCH=1) ونجاح فتح المنفذ.
        """
        if touch is None:
            return jsonify(ok=False, error="touch_disabled"), 503
        return Response(
            touch.stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/touch/cal")
    def touch_cal_get():
        return jsonify(_load_touch_cal())

    @app.post("/api/touch/cal")
    def touch_cal_set():
        # يُسمح من الكيوسك محلياً (127.0.0.1) بلا PIN — بيانات معايرة غير حسّاسة ولا
        # يملك المتصفّح الرمز؛ من الشبكة (Tailscale) يلزم PIN المشغّل.
        #
        # تنبيه أمني: ‪request.remote_addr‬ يكون 127.0.0.1 أيضاً للطلبات التي يمرّرها
        # وكيل عكسي (Tailscale Funnel) من الإنترنت عبر اللووباك، فيتجاوز الـPIN. لذا
        # نعتبر الطلب محلياً فقط إن لم يحمل ترويسات تمرير (XFF/Forwarded) — فالكيوسك
        # المحلي يخاطب Flask مباشرة بلا وكيل. (الدفاع الأساسي: ألّا يُمرِّر Funnel هذا
        # المسار أصلاً — راجع إعداد tailscale serve/funnel ليقصره على مسارات المشاركة.)
        forwarded = any(
            h in request.headers
            for h in ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded")
        )
        is_local = not forwarded and request.remote_addr in (
            "127.0.0.1", "::1", "::ffff:127.0.0.1",
        )
        if not (is_local or _check_pin()):
            return jsonify(ok=False, error="unauthorized"), 401
        body = request.get_json(silent=True) or {}
        cal = _load_touch_cal()
        for k in ("dTop", "dBottom", "minMm", "maxMm", "pressFrames", "releaseFrames", "cooldownMs", "rev"):
            if isinstance(body.get(k), (int, float)):
                cal[k] = body[k]
        if isinstance(body.get("calibrate"), bool):
            cal["calibrate"] = body["calibrate"]
        if isinstance(body.get("points"), list):
            cal["points"] = [
                {"d": float(p["d"]), "ny": float(p["ny"])}
                for p in body["points"]
                if isinstance(p, dict)
                and isinstance(p.get("d"), (int, float))
                and isinstance(p.get("ny"), (int, float))
            ]
        _save_touch_cal(cal)
        log.info("ضُبطت معايرة اللمس: %s", cal)
        return jsonify(ok=True, cal=cal)

    @app.get("/api/camera/orientation")
    def camera_orientation():
        """اتجاه اوتو-روتيت للكانون (من EXIF آخر التقاطة) لتدوير المعاينة الحية.

        بثّ Live View لا يحمل EXIF، لكن الالتقاط الكامل يحمله؛ فنعيد هنا زاوية
        الدوران (CSS) اللازمة لتظهر المعاينة بنفس اتجاه النتيجة. 0 إن لم تُعرف بعد
        أو في غير وضع gphoto2. الخريطة: EXIF 6→90، 8→270، 3→180، غير ذلك→0.
        """
        ori = camera.orientation if camera is not None else None
        rotate = {6: 90, 8: 270, 3: 180}.get(ori, 0)
        return jsonify(ok=True, orientation=ori, rotate=rotate)

    @app.post("/api/print")
    def print_photo():
        """طباعة الصورة النشطة عبر CUPS (الأمر lp).

        الطباعة لا تُنقص رصيد الباقة — ‪prints_used‬ إحصاء فقط (راجع session.py).
        المسار الحقيقي يُفعَّل بضبط ‪MIRROR_PRINTER‬ (اسم الطابعة في CUPS)؛ وبدونه
        في وضع المحاكاة نكتفي بالتسجيل حتى يبقى التطوير على الماك بلا طابعة سليماً.
        """
        if not settings.get("print_enabled"):
            return jsonify(ok=False, reason="print_disabled"), 403
        result = session.consume_print()
        if not result["ok"]:
            log.warning("رفض الطباعة: %s", result.get("reason"))
            return jsonify(result), 409

        copies = int(settings.get("copies") or app.config.get("COPIES_PER_PHOTO") or 1)
        printer = (app.config.get("PRINTER_NAME") or "").strip()

        # وضع المحاكاة بلا طابعة مضبوطة (تطوير على الماك): تسجيل فقط
        if app.config["MOCK_HARDWARE"] and not printer:
            log.info("طباعة (محاكاة) ×%s — المتبقي: %s", copies, result["remaining"])
            return jsonify(result)

        # مسار ملف الصورة النشطة (قاعدة الصورة الواحدة في photos.py)
        pid = photos.latest_id()
        url = photos.get(pid) if pid else None
        if not url:
            log.warning("لا توجد صورة نشطة للطباعة")
            return jsonify(ok=False, reason="no_active_photo"), 409
        photo_path = CAPTURES_DIR / url.rsplit("/", 1)[-1]
        if not photo_path.exists():
            log.warning("ملف الصورة غير موجود: %s", photo_path)
            return jsonify(ok=False, reason="photo_missing"), 409

        # إرسال المهمة إلى CUPS: 10×15 بلا حواف، ورق لامع، جودة 4 (أدنى/أسرع مستوى)
        cmd = ["lp"]
        if printer:
            cmd += ["-d", printer]
        cmd += [
            "-n", str(copies),
            "-o", "PageSize=4x6.Borderless",
            "-o", "MediaType=PhotographicGlossy",
            "-o", "print-quality=4",
            "-o", "fit-to-page",
            str(photo_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            log.error("فشل تشغيل أمر الطباعة: %s", exc)
            return jsonify(ok=False, reason="print_failed"), 500
        if proc.returncode != 0:
            log.error("رفض CUPS الطباعة (rc=%s): %s", proc.returncode, proc.stderr.strip())
            return jsonify(ok=False, reason="print_failed"), 500

        log.info(
            "طباعة صورة ×%s عبر %s — %s — المتبقي: %s",
            copies, printer or "الطابعة الافتراضية",
            proc.stdout.strip(), result["remaining"],
        )
        return jsonify(result)

    # ------------------------------------------------------------------ #
    # المشاركة الرقمية (QR ← صفحة محلية على جوال الضيف)
    # ------------------------------------------------------------------ #
    @app.get("/api/qr")
    def qr():
        """رمز QR (SVG) لبيانات نصية (رابط المشاركة)."""
        data = request.args.get("data", "")
        if not data:
            return jsonify(ok=False, error="missing data"), 400
        return Response(make_qr_svg(data), mimetype="image/svg+xml")

    @app.get("/api/photo/<photo_id>")
    def photo_info(photo_id: str):
        """رابط صورة بالمعرّف — تستخدمه صفحة المشاركة على الجوال."""
        url = photos.get(photo_id)
        if not url:
            return jsonify(ok=False, error="not found"), 404
        return jsonify(ok=True, photo_url=url)

    @app.post("/api/share")
    def share_count():
        """تسجيل مشاركة رقمية (للإحصاء في لوحة المشغّل)."""
        return jsonify(session.consume_share())

    @app.get("/p/<photo_id>")
    def share_page(photo_id: str):
        """صفحة المشاركة (تُفتح على جوال الضيف بعد مسح QR)."""
        return send_from_directory(FRONTEND_DIR, "share.html")

    @app.get("/latest")
    def latest_photo():
        """مشاركة آخر صورة ملتقطة بلمسة NFC واحدة (مع حماية الخصوصية).

        يُكتب هذا الرابط الثابت على ستيكر NFC مرّة واحدة؛ وعند لمسه يحوّل
        جوال الضيف إلى صفحة صورته (/p/<photo_id>) — لكن فقط إن كانت الصورة
        حديثة (ضمن النافذة الزمنية) ولم تُستهلك بعد (عند تفعيل الاستخدام لمرة).
        وإلا تظهر صفحة لطيفة بدل كشف صورة غيره.
        """
        ttl = app.config["LATEST_TTL"] or None
        once = app.config["LATEST_ONCE"]
        photo_id = photos.latest_id(ttl=ttl, unclaimed=once)
        if not photo_id:
            return send_from_directory(FRONTEND_DIR, "no_photo.html")
        if once:
            photos.claim(photo_id)
        return redirect(f"/p/{photo_id}", code=302)

    # ------------------------------------------------------------------ #
    # لوحة المشغّل (محمية برمز PIN)
    # ------------------------------------------------------------------ #
    # حماية من تخمين الرمز (مهمّة عند كشف اللوحة عبر Tailscale Funnel للإنترنت):
    # بعد عدّة محاولات خاطئة متتالية يُقفل التحقّق مؤقّتاً فيصبح التخمين الآلي غير عملي.
    pin_guard = {"fails": 0, "locked_until": 0.0}
    PIN_MAX_FAILS = 5
    PIN_LOCK_SECS = 60

    def _verify_pin(candidate: str) -> bool:
        now = time.time()
        if pin_guard["locked_until"] > now:
            return False  # مقفل مؤقّتاً — حتى الرمز الصحيح يُرفض خلال فترة القفل
        if candidate == settings.pin:
            pin_guard["fails"] = 0
            return True
        pin_guard["fails"] += 1
        if pin_guard["fails"] >= PIN_MAX_FAILS:
            pin_guard["locked_until"] = now + PIN_LOCK_SECS
            pin_guard["fails"] = 0
            log.warning("قفل تحقّق الرمز %s ثانية بعد محاولات خاطئة متتالية", PIN_LOCK_SECS)
        return False

    def _check_pin() -> bool:
        return _verify_pin(request.headers.get("X-Admin-Pin", ""))

    @app.post("/api/admin/login")
    def admin_login():
        """التحقق من رمز المشغّل (مع حماية من التخمين)."""
        data = request.get_json(silent=True) or {}
        ok = _verify_pin(str(data.get("pin", "")))
        return (jsonify(ok=True), 200) if ok else (jsonify(ok=False), 401)

    @app.get("/api/settings")
    def get_settings():
        """قراءة الإعدادات العامة (تستخدمها واجهة الضيف)."""
        return jsonify(ok=True, settings=settings.public())

    @app.put("/api/settings")
    def put_settings():
        """تعديل الإعدادات — يتطلّب رمز المشغّل."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        updated = settings.update(data)
        log.info("تحديث الإعدادات: %s", list(data.keys()))
        return jsonify(ok=True, settings=updated)

    @app.post("/api/admin/pin")
    def change_pin():
        """تغيير رمز المشغّل — يتطلّب الرمز الحالي."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        new_pin = str(data.get("new_pin", "")).strip()
        if len(new_pin) < 4:
            return jsonify(ok=False, error="pin_too_short"), 400
        settings.change_pin(new_pin)
        log.info("تم تغيير رمز المشغّل")
        return jsonify(ok=True)

    @app.post("/api/admin/overlay")
    def upload_overlay():
        """رفع إطار/شعار (PNG) للمناسبة — يتطلّب الرمز."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        file = request.files.get("overlay")
        if not file or not file.filename.lower().endswith(".png"):
            return jsonify(ok=False, error="png_required"), 400
        OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        file.save(OVERLAY_PATH)
        settings.set_overlay(True)
        log.info("تم رفع إطار المناسبة")
        return jsonify(ok=True)

    @app.delete("/api/admin/overlay")
    def remove_overlay():
        """إزالة الإطار — يتطلّب الرمز."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        if OVERLAY_PATH.exists():
            OVERLAY_PATH.unlink()
        settings.set_overlay(False)
        return jsonify(ok=True)

    # شاشة التوقّف (ثيم المناسبة) — صورة اختيارية تُعرض عند خمول الكشك
    SCREENSAVER_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
    ASSETS_DIR = FRONTEND_DIR / "assets"

    def _clear_screensaver_files():
        for p in ASSETS_DIR.glob("screensaver.*"):
            try:
                p.unlink()
            except OSError:
                pass

    @app.post("/api/admin/screensaver")
    def upload_screensaver():
        """رفع صورة شاشة التوقّف (PNG/JPG/WEBP) — يتطلّب الرمز."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        file = request.files.get("image")
        if not file or not file.filename:
            return jsonify(ok=False, error="image_required"), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in SCREENSAVER_EXTS:
            return jsonify(ok=False, error="bad_type"), 400
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        _clear_screensaver_files()  # لا نُبقي امتداداً قديماً
        file.save(ASSETS_DIR / f"screensaver{ext}")
        # رابط عام مع بصمة زمن لإبطال التخزين المؤقت عند كل رفع
        url = f"/assets/screensaver{ext}?v={int(time.time())}"
        settings.set_screensaver(url)
        log.info("تم رفع صورة شاشة التوقّف")
        return jsonify(ok=True, screensaver=url)

    @app.delete("/api/admin/screensaver")
    def remove_screensaver():
        """إلغاء شاشة التوقّف — يتطلّب الرمز."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        _clear_screensaver_files()
        settings.set_screensaver("")
        return jsonify(ok=True)

    # --- تحكّم الجلسة (محمي) ---
    @app.post("/api/session/extend")
    def session_extend():
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        state = session.extend(
            add_photos=int(data.get("add_photos", 0) or 0),
            add_minutes=int(data.get("add_minutes", 0) or 0),
        )
        log.info("تمديد الجلسة: +%s صورة +%s د", data.get("add_photos"), data.get("add_minutes"))
        return jsonify(ok=True, **state)

    @app.post("/api/session/pause")
    def session_pause():
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        return jsonify(ok=True, **session.set_paused(bool(data.get("paused", True))))

    @app.post("/api/session/end")
    def session_end():
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        log.info("إنهاء الجلسة يدوياً")
        return jsonify(ok=True, **session.end())

    @app.post("/api/session/reset")
    def session_reset():
        """بدء مناسبة جديدة (ضبط الحدّ وتصفير العدّاد) — يتطلّب رمز المشغّل."""
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        state = session.reset(
            photo_limit=data.get("photo_limit"),
            duration_minutes=data.get("session_minutes"),
        )
        log.info("جلسة جديدة: حدّ=%s مدة=%s د", state["limit"], state["session_minutes"])
        return jsonify(ok=True, **state)

    # --- تحكّم الجهاز (إطفاء / إعادة تشغيل — محمي) ---
    @app.post("/api/system/reboot")
    def system_reboot():
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        log.info("طلب إعادة تشغيل الجهاز من لوحة المشغّل")
        return jsonify(ok=True, scheduled=schedule_system_power("reboot"), action="reboot")

    @app.post("/api/system/poweroff")
    def system_poweroff():
        if not _check_pin():
            return jsonify(ok=False, error="unauthorized"), 401
        log.info("طلب إطفاء الجهاز من لوحة المشغّل")
        return jsonify(ok=True, scheduled=schedule_system_power("poweroff"), action="poweroff")

    return app


app = create_app()


if __name__ == "__main__":
    # تفعيل HTTPS تلقائياً عند وجود شهادة محلية (يلزم للحفظ بضغطة واحدة على iOS)
    ssl_context = None
    scheme = "http"
    if CERT_PATH.exists() and KEY_PATH.exists():
        ssl_context = (str(CERT_PATH), str(KEY_PATH))
        scheme = "https"
    log.info("تشغيل مرآة الفوتوبوث على %s://%s:%s", scheme, Config.HOST, Config.PORT)
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        ssl_context=ssl_context,
        threaded=True,  # يلزم لبثّ المعاينة MJPEG مع خدمة بقية الطلبات بالتوازي
    )
