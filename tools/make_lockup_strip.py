#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مولّد قفل العلامة الأفقي لشريط اللوقو السفلي في الصور.

ينتج ملفاً واحداً جاهزاً: frontend/assets/brand/qamra-lockup-row.png
= رمز الكاميرا (mark-ink.png) + كلمة QAMRA محاذاةً مسبقاً، بخلفية شفّافة.

لماذا صورة واحدة مخبوزة؟ كانت camera.js ترسم الرمز ثم تكتب "QAMRA" كنصّ حيّ
على الكانفس وقت الالتقاط. ذلك يعتمد على تحميل الخط ومقاييس الكانفس، ويوسّط
الرمز والنصّ بحسابين مختلفين — فينتج قفلٌ مائل/بخطّ احتياطي أحياناً (العيوب التي
ظهرت على الطبعات). خبز القفل مرّة واحدة هنا يلغي كل ذلك: الفرونت-إند يرسم صورة
واحدة موسّطة فقط.

ملاحظات تصميمية مخبوزة أدناه (عدّلها ثم أعد التشغيل عند الحاجة):
  - كلمة QAMRA لاتينية؛ تُرسم من الوجه اللاتيني Tajawal (tajawal-latin-300.woff2)
    لأن ملف الوزن 500 عربيّ الحروف فقط (لا يحوي حروفاً لاتينية).
  - لون الكلمة مطابق لحبر الرمز (≈ #0e0e0e) ليقرآ كوحدة واحدة.
  - ارتفاع الكابيتال ≈ 0.52 من ارتفاع حبر الرمز، والفجوة ≈ 0.28 منه.
  - الرمز يُقصّ أولاً إلى حبره الفعلي (فيه هامش شفّاف)، والناتج يُقصّ محكماً.

التشغيل (من جذر المستودع):  python3 tools/make_lockup_strip.py
يتطلب: Pillow, fonttools, brotli  (brotli لفكّ ضغط woff2).
"""

from pathlib import Path

from fontTools.ttLib import woff2
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MARK = ROOT / "frontend/assets/brand/mark-ink.png"
WOFF2 = ROOT / "frontend/fonts/tajawal-latin-300.woff2"
OUT = ROOT / "frontend/assets/brand/qamra-lockup-row.png"

INK = (14, 14, 14)      # حبر مطابق للرمز
MARK_H = 600            # ارتفاع مرجعي عالي الدقة للرمز (يبقى حاداً عند 2048عرض للـDSLR)
CAP_FRAC = 0.52         # ارتفاع كابيتال الكلمة نسبةً لارتفاع حبر الرمز
GAP_FRAC = 0.28         # الفجوة بين الرمز والكلمة نسبةً لارتفاع الرمز
LETTER_SP = 0.06        # تباعد الحروف نسبةً لحجم الخط
WORD = "QAMRA"


def _trim_alpha(img, thresh=12):
    """يقصّ صورة RGBA إلى حدود حبرها الفعلي (ألفا > thresh)."""
    a = img.split()[-1]
    return img.crop(a.point(lambda p: 255 if p > thresh else 0).getbbox())


def main():
    ttf = OUT.parent / "_tajawal-latin-300.ttf"  # مؤقّت
    woff2.decompress(str(WOFF2), str(ttf))
    try:
        # الرمز مقصوصاً ومُحجّماً
        mark = _trim_alpha(Image.open(MARK).convert("RGBA"))
        mw, mh = mark.size
        mark = mark.resize((round(mw * MARK_H / mh), MARK_H), Image.LANCZOS)
        mw, mh = mark.size

        # قياس نسبة الكابيتال/الـem لهذا الوجه (مستقلّ عن النسخة)
        probe = ImageFont.truetype(str(ttf), 1000)
        pim = Image.new("L", (5000, 2500), 0)
        ImageDraw.Draw(pim).text((100, 600), WORD, font=probe, fill=255)
        bb = pim.getbbox()
        cap_per_em = (bb[3] - bb[1]) / 1000.0

        em = round((CAP_FRAC * mh) / cap_per_em)
        font = ImageFont.truetype(str(ttf), em)
        ls = round(em * LETTER_SP)

        # ارسم الكلمة حرفاً حرفاً (لتطبيق التباعد) ثم اقصص محكماً
        pad = em
        tmp = Image.new("RGBA", (em * 7, em * 3), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        x = pad
        for ch in WORD:
            d.text((x, pad), ch, font=font, fill=INK + (255,))
            x += d.textlength(ch, font=font) + ls
        word = tmp.crop(tmp.getbbox())
        ww, wh = word.size

        # تركيب أفقي: [الرمز][فجوة][الكلمة]، الكلمة موسّطة على مركز الرمز
        gap = round(GAP_FRAC * mh)
        canvas = Image.new("RGBA", (mw + gap + ww, mh), (0, 0, 0, 0))
        canvas.alpha_composite(mark, (0, 0))
        canvas.alpha_composite(word, (mw + gap, round((mh - wh) / 2)))
        canvas = canvas.crop(canvas.getbbox())
        canvas.save(OUT)
        print(f"كُتب {OUT.relative_to(ROOT)}  {canvas.size}  نسبة={canvas.size[0] / canvas.size[1]:.4f}")
    finally:
        ttf.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
