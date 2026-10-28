"""واجهة gphoto2 لكاميرا Canon EOS 4000D (الخطوة ٥).

غلاف حول أداة gphoto2 في سطر الأوامر يوفّر:
- ``capture()`` : التقاط صورة نهائية عبر ``--capture-image-and-download`` وإرجاع بايتات JPEG.
- ``preview_stream()`` : مولّد يبثّ إطارات JPEG من Live View عبر ``--capture-movie``
  (تُغلَّف لاحقاً كـ multipart/x-mixed-replace في الخادم — المسار أ).

قيد حرج: Live View والالتقاط **لا يعملان معاً** على نفس الاتصال، لذا قفلٌ واحد
(``threading.Lock``) يضمن عدم تداخلهما — عند الالتقاط نوقف بثّ المعاينة أولاً ثم نلتقط.

ملاحظات بيئة البوث (موثّقة في docs/camera-gphoto2.md):
- **Wi-Fi في الكاميرا يجب أن يكون Disable** وإلا تُعطّل كانون منفذ USB كلياً فلا تظهر.
- **Auto power off يجب أن يكون Disable** وإلا تنام الكاميرا ويسقط الاتصال أثناء التشغيل.
- تعارض gvfs مُعالَج **دائماً** بتقنيع خدمة ``gvfs-gphoto2-volume-monitor`` على مستوى
  المستخدم على البوث، فلا حاجة لقتل gvfs من هنا.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("mirror.camera")

# علامتا إطار JPEG للفصل داخل بثّ MJPEG الخام من --capture-movie
_SOI = b"\xff\xd8"  # بداية صورة (Start Of Image)
_EOI = b"\xff\xd9"  # نهاية صورة (End Of Image)


class CameraError(RuntimeError):
    """فشل التواصل مع الكاميرا (غير موصولة، مهلة انتهت، أو خطأ من gphoto2)."""


class Gphoto2Camera:
    """تحكّم بكاميرا DSLR عبر gphoto2 مع قفل يمنع تداخل المعاينة والالتقاط."""

    def __init__(
        self,
        bin_path: str = "gphoto2",
        capture_timeout: float = 25.0,
        state_path: str | Path | None = None,
    ):
        self._bin = bin_path
        self._capture_timeout = capture_timeout
        self._lock = threading.Lock()  # يحرس انتقالات الجهاز (معاينة ⇄ التقاط)
        self._preview_proc: subprocess.Popen | None = None
        # اتجاه اوتو-روتيت الكانون: يُقرأ من وسم EXIF لكل التقاطة ويُحفظ ليثبت بين
        # عمليات التشغيل، فتتبعه المعاينة الحية (التي لا تحمل EXIF بنفسها).
        self._state_path = Path(state_path) if state_path else None
        self._orientation: int | None = self._load_orientation()

    # ------------------------------------------------------------------ #
    # اتجاه الصورة (اوتو-روتيت) — لمزامنة المعاينة الحية مع النتيجة
    # ------------------------------------------------------------------ #
    @property
    def orientation(self) -> int | None:
        """قيمة وسم EXIF للاتجاه (1..8) لآخر التقاطة، أو None إن لم تُعرف بعد."""
        return self._orientation

    def _load_orientation(self) -> int | None:
        if self._state_path and self._state_path.exists():
            try:
                return int(self._state_path.read_text().strip()) or None
            except (OSError, ValueError):
                return None
        return None

    def _save_orientation(self, ori: int) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(str(int(ori)))
        except OSError:
            pass

    @staticmethod
    def _parse_exif_orientation(data: bytes) -> int | None:
        """يقرأ وسم اتجاه EXIF (0x0112) من بايتات JPEG بلا مكتبات خارجية.

        يعيد القيمة (1..8) أو None إن لم تُوجد. تحليل مبسّط: نمرّ على مقاطع JPEG
        حتى APP1 (Exif)، نقرأ ترويسة TIFF ثم IFD0 بحثاً عن وسم الاتجاه.
        """
        try:
            if data[:2] != b"\xff\xd8":  # SOI
                return None
            i, n = 2, len(data)
            while i + 4 <= n:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xD9, 0xDA):  # EOI أو بداية بيانات الصورة
                    break
                seg_len = (data[i + 2] << 8) | data[i + 3]
                if seg_len < 2:
                    break
                seg_start = i + 4
                if marker == 0xE1 and data[seg_start : seg_start + 6] == b"Exif\x00\x00":
                    tiff = seg_start + 6
                    order = data[tiff : tiff + 2]
                    if order == b"II":
                        le = True
                    elif order == b"MM":
                        le = False
                    else:
                        return None
                    bo = "little" if le else "big"
                    ifd0 = tiff + int.from_bytes(data[tiff + 4 : tiff + 8], bo)
                    count = int.from_bytes(data[ifd0 : ifd0 + 2], bo)
                    for k in range(count):
                        ent = ifd0 + 2 + k * 12
                        if int.from_bytes(data[ent : ent + 2], bo) == 0x0112:
                            return int.from_bytes(data[ent + 8 : ent + 10], bo)
                    return None
                i = i + 2 + seg_len
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # أدوات داخلية
    # ------------------------------------------------------------------ #
    def _kill_preview_locked(self) -> None:
        """يوقف عملية بثّ المعاينة إن وُجدت (يُستدعى داخل القفل فقط)."""
        proc, self._preview_proc = self._preview_proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

    # ------------------------------------------------------------------ #
    # الالتقاط النهائي (المسار الأضمن في gphoto2)
    # ------------------------------------------------------------------ #
    def capture(self) -> bytes:
        """يلتقط صورة، ينزّلها للبوث، ويعيد بايتات JPEG.

        يوقف المعاينة أولاً (لا تتداخل مع الالتقاط على نفس الاتصال)، يمنح الكاميرا
        لحظة للخروج من وضع Live View، ثم يلتقط. يعيد المحاولة عند خطأ "الجهاز مشغول"
        العابر الذي يظهر أحياناً مباشرة بعد إيقاف المعاينة. يرفع ``CameraError`` عند الفشل.
        """
        with self._lock:
            self._kill_preview_locked()
            time.sleep(0.25)  # دع الكاميرا تستقرّ بعد الخروج من Live View قبل الالتقاط
            last_err: CameraError | None = None
            for attempt in range(3):
                try:
                    return self._capture_once()
                except CameraError as exc:
                    last_err = exc
                    msg = str(exc).lower()
                    busy = "busy" in msg or "i/o in progress" in msg or "0x2019" in msg
                    if busy and attempt < 2:
                        log.warning("الكاميرا مشغولة — إعادة محاولة الالتقاط (%d)", attempt + 1)
                        time.sleep(0.6)
                        continue
                    raise
            raise last_err  # لا يُفترض الوصول هنا، لكن للسلامة

    def _capture_once(self) -> bytes:
        """محاولة التقاط واحدة عبر gphoto2 (تُستدعى داخل القفل)."""
        tmp = Path(tempfile.gettempdir()) / f"qamra-cap-{uuid.uuid4().hex[:8]}.jpg"
        try:
            proc = subprocess.run(
                [
                    self._bin,
                    "--capture-image-and-download",
                    "--filename", str(tmp),
                    "--force-overwrite",
                ],
                capture_output=True,
                timeout=self._capture_timeout,
            )
        except subprocess.TimeoutExpired:
            raise CameraError("انتهت مهلة الالتقاط")
        except FileNotFoundError:
            raise CameraError("gphoto2 غير مثبّت")

        if proc.returncode != 0 or not tmp.exists():
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise CameraError(err or "فشل الالتقاط")
        try:
            data = tmp.read_bytes()
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        if not data:
            raise CameraError("صورة فارغة")
        # حدّث اتجاه اوتو-روتيت من EXIF (تتبعه المعاينة الحية لاحقاً)
        ori = self._parse_exif_orientation(data)
        if ori and ori != self._orientation:
            self._orientation = ori
            self._save_orientation(ori)
            log.info("اتجاه الكانون (EXIF) = %s", ori)
        return data

    # ------------------------------------------------------------------ #
    # معاينة Live View (المسار أ)
    # ------------------------------------------------------------------ #
    def preview_stream(self):
        """مولّد يبثّ إطارات JPEG كاملة من Live View.

        يُنهى تلقائياً عند الالتقاط (لأن ``capture()`` يقتل عملية المعاينة)،
        وعندها ينتهي المولّد بسلام. يرفع ``CameraError`` إن تعذّر بدء gphoto2.
        """
        with self._lock:
            self._kill_preview_locked()
            try:
                proc = subprocess.Popen(
                    [self._bin, "--capture-movie", "--stdout"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except FileNotFoundError:
                raise CameraError("gphoto2 غير مثبّت")
            self._preview_proc = proc

        buf = bytearray()
        try:
            while True:
                chunk = proc.stdout.read(16384)
                if not chunk:
                    break  # انتهت العملية (قُتلت للالتقاط، أو فُصلت الكاميرا)
                buf.extend(chunk)
                # استخرج كل الإطارات المكتملة الموجودة في المخزن
                while True:
                    start = buf.find(_SOI)
                    if start < 0:
                        buf.clear()  # لا بداية إطار — تخلّص من الضجيج
                        break
                    end = buf.find(_EOI, start + 2)
                    if end < 0:
                        if start > 0:
                            del buf[:start]  # احتفظ من بداية الإطار الجزئي
                        break
                    yield bytes(buf[start : end + 2])
                    del buf[: end + 2]
        finally:
            with self._lock:
                if self._preview_proc is proc:
                    self._preview_proc = None
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
