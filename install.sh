#!/usr/bin/env bash
# Google Cloud serverida bir marta ishga tushiriladi:
#   curl -fsSL https://raw.githubusercontent.com/FOYDALANUVCHI/kahoot-jurnal-bot/main/install.sh | sudo bash -s https://github.com/FOYDALANUVCHI/kahoot-jurnal-bot.git
set -euo pipefail
REPO="${1:?GitHub repozitoriy manzilini bering}"
DIR=/opt/kahoot-jurnal-bot

apt-get update -y
apt-get install -y python3-venv git

# 1 GB xotira kam, pip o'rnatishda yiqilmasligi uchun swap
if ! swapon --show | grep -q swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
if [ ! -f "$DIR/.env" ]; then
  if [ -f "$DIR/.env.example" ]; then cp "$DIR/.env.example" "$DIR/.env"
  else printf 'TELEGRAM_TOKEN=\nADMIN_IDS=\nSPREADSHEET_ID=\nGEMINI_API_KEY=\nGEMINI_MODEL=gemini-flash-lite-latest\nTZ_NAME=Asia/Tashkent\n' > "$DIR/.env"; fi
fi
chmod 600 "$DIR/.env"

cat > /etc/systemd/system/kahoot-bot.service <<UNIT
[Unit]
Description=Kahoot -> baholash jurnali Telegram boti
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# GitHub'dagi o'zgarishlarni har 10 daqiqada olib, botni qayta ishga tushiradi
cat > /usr/local/bin/kahoot-bot-update <<UPD
#!/usr/bin/env bash
cd $DIR
OLD=\$(git rev-parse HEAD)
git pull -q --ff-only || exit 0
NEW=\$(git rev-parse HEAD)
if [ "\$OLD" != "\$NEW" ]; then
  $DIR/venv/bin/pip install -q -r requirements.txt
  systemctl restart kahoot-bot
fi
UPD
chmod +x /usr/local/bin/kahoot-bot-update

cat > /etc/systemd/system/kahoot-bot-update.service <<UNIT
[Unit]
Description=Kahoot bot: GitHub'dan yangilash
[Service]
Type=oneshot
ExecStart=/usr/local/bin/kahoot-bot-update
UNIT
cat > /etc/systemd/system/kahoot-bot-update.timer <<UNIT
[Unit]
Description=Kahoot bot: har 10 daqiqada yangilanishni tekshirish
[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable kahoot-bot kahoot-bot-update.timer
systemctl start kahoot-bot-update.timer

echo
echo "O'rnatildi. Endi sozlamalarni kiriting:"
echo "  sudo nano $DIR/.env"
echo "So'ng botni ishga tushiring:"
echo "  sudo systemctl restart kahoot-bot && sudo journalctl -u kahoot-bot -f"
