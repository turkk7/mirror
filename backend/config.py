"""إعدادات التطبيق المركزية.

كل قيمة قابلة للتهيئة من متغيرات البيئة، مع قيمة افتراضية آمنة للتطوير.
"""

import os
from pathlib import Path

# المسارات الأساسية
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
CAPTURES_DIR = BASE_DIR / "captures"  # حفظ الصور الملتقطة
DATA_DIR = BASE_DIR / "data"  # الإعدادات الدائمة
SETTINGS_PATH = DATA_DIR / "settings.json"
OVERLAY_PATH = FRONTEND_DIR / "assets" / "overlay.png"  # إطار/شعار المناسبة

# شهادة HTTPS المحلية (لتمكين الحفظ بضغطة واحدة عبر قائمة مشاركة iOS)
CERT_DIR = BASE_DIR / "certs"
CERT_PATH = CERT_DIR / "cert.pem"
KEY_PATH = CERT_DIR / "key.pem"


class Config:
    # الخادم
    HOST = os.environ.get("MIRROR_HOST", "0.0.0.0")
    PORT = int(os.environ.get("MIRROR_PORT", "8000"))
    # التنقيح اختياري بالطلب: الافتراضي معطّل (مُنقّح Werkzeug يتيح RCE عند الربط
    # على 0.0.0.0، والمُعيد يفتح منفذ اللمس مرّتين). للتطوير: MIRROR_DEBUG=1 ./run.sh
    DEBUG = os.environ.get("MIRROR_DEBUG", "0") == "1"

    # عنوان ثابت لروابط المشاركة (QR/التاق) بدل عنوان IP المتغيّر.
    # مثال: mirror.local — إن تُرك فارغاً نستخدم عنوان IP الحالي للشبكة.
    PUBLIC_HOST = os.environ.get("MIRROR_PUBLIC_HOST", "").strip()

    # عنوان الأساس الكامل لروابط المشاركة عند الكشف للإنترنت (مثل Tailscale Funnel):
    # مثال: https://qamra.xxxx.ts.net — إن ضُبط، تُبنى روابط QR/المشاركة عليه مباشرة
    # (بلا منفذ، وبمخطط https)، فيعمل مسح QR من جوال الضيف على بيانات الجوال.
    # إن تُرك فارغاً نرجع للعنوان المحلي (http://<ip>:<port>).
    PUBLIC_BASE = os.environ.get("MIRROR_PUBLIC_BASE", "").strip()

    # وضع المحاكاة: يعمل بدون كاميرا/طابعة حقيقية (للتطوير على macOS)
    MOCK_HARDWARE = os.environ.get("MIRROR_MOCK", "1") == "1"

    # مصدر الكاميرا:
    #   webcam  = كاميرا المتصفح (getUserMedia) — للاختبار على الماك/أي جهاز
    #   mock    = صورة عيّنة ثابتة
    #   gphoto2 = كاميرا DSLR (Canon EOS 4000D) على البوث عبر gphoto2 — الخطوة ٥
    CAMERA_MODE = os.environ.get("MIRROR_CAMERA", "webcam")

    # إعدادات gphoto2 (تُستخدم فقط عند CAMERA_MODE=gphoto2 و MOCK=0)
    GPHOTO2_BIN = os.environ.get("MIRROR_GPHOTO2_BIN", "gphoto2")
    CAPTURE_TIMEOUT = float(os.environ.get("MIRROR_CAPTURE_TIMEOUT", "25"))

    # طبقة اللمس (حسّاس ToF واحد عبر المنفذ التسلسلي، يُبثّ للواجهة بـSSE):
    #   TOUCH_ENABLED = تشغيل جسر اللمس في الباك-إند (يلزم على البوث؛ لأن كروميوم-snap
    #                   لا يفتح المنفذ عبر Web Serial). الافتراضي معطّل (دِف/ماك).
    #   TOUCH_PORT    = مسار المنفذ؛ فارغ = اكتشاف تلقائي (/dev/ttyACM* ثم /dev/ttyUSB*).
    TOUCH_ENABLED = os.environ.get("MIRROR_TOUCH", "0") == "1"
    TOUCH_PORT = os.environ.get("MIRROR_TOUCH_PORT", "").strip()

    # خصوصية مشاركة NFC (/latest):
    #   LATEST_TTL  = عمر الصورة بالثواني قبل حذفها تلقائياً (0 = بلا حد)
    #                 وأي التقاطة أحدث تحذف السابقة فوراً بغض النظر عن الوقت.
    #   LATEST_ONCE = تسليم لأول لامس فقط ثم تُقفل (استخدام لمرة واحدة)
    LATEST_TTL = int(os.environ.get("MIRROR_LATEST_TTL", "180"))
    LATEST_ONCE = os.environ.get("MIRROR_LATEST_ONCE", "1") == "1"

    # رفع كل صورة لخدمة المشاركة العامة (VPS) ليأخذها الضيف عبر إنترنته الخاص
    # (بلا شبكة البوث). فارغ = معطّل (الافتراضي للتطوير)؛ يُفعّل على البوث بضبط
    # العنوان والمفتاح. الرفع غير معطِّل للتدفّق وآمن عند انقطاع الشبكة.
    CLOUD_UPLOAD_URL = os.environ.get("MIRROR_CLOUD_UPLOAD_URL", "").strip()
    CLOUD_UPLOAD_KEY = os.environ.get("MIRROR_CLOUD_UPLOAD_KEY", "").strip()
    CLOUD_UPLOAD_TIMEOUT = float(os.environ.get("MIRROR_CLOUD_UPLOAD_TIMEOUT", "20"))

    # إعدادات الجلسة الافتراضية (تُضبط لكل مناسبة لاحقاً)
    SESSION_DURATION_MINUTES = int(os.environ.get("MIRROR_SESSION_MINUTES", "180"))
    SESSION_PHOTO_LIMIT = int(os.environ.get("MIRROR_PHOTO_LIMIT", "100"))

    # الطباعة
    PRINTER_NAME = os.environ.get("MIRROR_PRINTER", "")  # فارغ = الطابعة الافتراضية
    COPIES_PER_PHOTO = int(os.environ.get("MIRROR_COPIES", "1"))

    # لوحة المشغّل: رمز حماية بسيط (غيّره لكل جهاز)
    ADMIN_PIN = os.environ.get("MIRROR_ADMIN_PIN", "1234")
