#!/usr/bin/env bash
# تشغيل مرآة الفوتوبوث: ينشئ بيئة افتراضية، يثبّت المتطلبات، ويشغّل الخادم.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "→ إنشاء البيئة الافتراضية…"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "→ تثبيت المتطلبات…"
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

# عنوان ثابت لروابط المشاركة: اسم Bonjour (.local) لا يتغيّر مع تبدّل IP
if [ -z "${MIRROR_PUBLIC_HOST:-}" ]; then
  LH=$(scutil --get LocalHostName 2>/dev/null || true)
  [ -n "$LH" ] && export MIRROR_PUBLIC_HOST="${LH}.local"
fi

echo "→ العنوان الثابت لروابط المشاركة: ${MIRROR_PUBLIC_HOST:-(IP الحالي)}"
echo "→ تشغيل الخادم على http://localhost:${MIRROR_PORT:-8000}"
cd backend
exec python app.py
