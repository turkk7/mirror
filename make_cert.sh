#!/usr/bin/env bash
# يولّد شهادة HTTPS محلية موقّعة ذاتياً تتضمن عنوان الجهاز على الشبكة (SAN)،
# لتمكين الحفظ بضغطة واحدة عبر قائمة مشاركة iOS. تُنشأ مرة واحدة.
set -euo pipefail
cd "$(dirname "$0")"

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)
mkdir -p certs

echo "→ توليد شهادة للعنوان: ${IP}"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -days 825 -subj "/CN=mirror" \
  -addext "subjectAltName=IP:${IP},IP:127.0.0.1,DNS:localhost"

echo "✓ تم: certs/cert.pem + certs/key.pem"
echo "  عنوان المرآة سيصبح: https://${IP}:8000"
echo "  لثقة آيفونك بالشهادة: أرسل certs/cert.pem للجوال ونصّبه، ثم فعّل الثقة الكاملة من:"
echo "  الإعدادات ← عام ← حول ← إعدادات ثقة الشهادات."
