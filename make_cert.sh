#!/usr/bin/env bash
# يولّد شهادة HTTPS محلية موقّعة ذاتياً تتضمن عنوان الجهاز على الشبكة (SAN)،
# لتمكين الحفظ بضغطة واحدة عبر قائمة مشاركة iOS. تُنشأ مرة واحدة.
set -euo pipefail
cd "$(dirname "$0")"

# عنوان الجهاز على الشبكة المحلية — يدعم ماك ولينكس (البوث أوبونتو)، أو مرّره صراحةً
# كوسيط أول:  ./make_cert.sh 192.168.1.147
IP="${1:-}"
if [ -z "$IP" ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)     # ماك
  [ -n "$IP" ] || IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')             # لينكس
  [ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}')                            # لينكس (بديل)
  [ -n "$IP" ] || IP=127.0.0.1
fi

# اسم المضيف للمشاركة (روابط HTTPS تستخدمه) — نضيفه كـDNS SAN وإلا رفضته الجوّالات
# حتى مع ثقتها بالشهادة. إن لم يُضبط، نكتشف اسم Bonjour على ماك (كما في run.sh).
HOST="${MIRROR_PUBLIC_HOST:-}"
if [ -z "$HOST" ]; then
  LH=$(scutil --get LocalHostName 2>/dev/null || true)
  [ -n "$LH" ] && HOST="${LH}.local"
fi
SAN="IP:${IP},IP:127.0.0.1,DNS:localhost"
[ -n "$HOST" ] && SAN="${SAN},DNS:${HOST}"

mkdir -p certs

echo "→ توليد شهادة للعنوان: ${IP}${HOST:+ + ${HOST}}"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -days 825 -subj "/CN=mirror" \
  -addext "subjectAltName=${SAN}"

echo "✓ تم: certs/cert.pem + certs/key.pem"
echo "  عنوان المرآة سيصبح: https://${HOST:-$IP}:8000"
echo "  لثقة آيفونك بالشهادة: أرسل certs/cert.pem للجوال ونصّبه، ثم فعّل الثقة الكاملة من:"
echo "  الإعدادات ← عام ← حول ← إعدادات ثقة الشهادات."
