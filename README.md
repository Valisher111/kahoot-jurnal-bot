# Kahoot → Baholash jurnali boti

Fan guruhiga Kahoot hisobotini tashlaysiz, bot ballarni jurnalga o'zi yozadi.

- **Excel hisobot** (Kahoot → Reports → o'yin → Download report): to'g'ri javoblar ulushi × 10 = kunlik ball.
- **Skrinshot**: Gemini orqali o'qiladi (ixtiyoriy, bepul API kalit kerak).
- Ball o'sha kungi dars ustuniga yoziladi. Guruh jurnal varag'i Telegram guruh nomidagi raqamdan topiladi (masalan "Listening 106" → 106 varag'i).
- Faqat siz yuborgan fayllar qabul qilinadi. Natija sizga shaxsiy xabarda keladi, talabalar ko'rmaydi.

Izohga (caption) yozish mumkin:

| Izoh | Ma'nosi |
|---|---|
| `25.10` | boshqa sana ustuniga yozish |
| `#223` | guruhni aniq ko'rsatish |
| `!` | oldin qo'yilgan ball ustidan yozish |
| `12 savol` | savollar soni (skrinshotda ko'rinmasa) |

## Ovozli fikr

Botga **shaxsiy chatda** ovozli xabar yuboring, masalan:
"223-guruh. Jahona bugun juda faol bo'ldi, Sabrina harakat qildi, Sevinchning uy ishi yaxshi emas, Nigina kelmadi."

1. AI (Gemini) ovozni tinglab, kim haqida nima deyilganini toifaga ajratadi: a'lo, yaxshi, harakat, passiv, salbiy, kelmadi yoki aniq aytilgan ball.
2. **Ballni AI emas, `mezon.json` dagi qoida hisoblaydi**: toifa + talabaning oxirgi 5 ta bahosi o'rtachasi. O'sha kuni jurnalda Kahoot bali bo'lsa, ikkalasining o'rtachasi olinadi. Kelgan talaba 5 dan kam olmaydi, 10 dan oshmaydi.
3. Bot taklifni ko'rsatadi: "Jahona: 5.5 → 7.8 (juda faol; o'rtacha 9.0, jurnaldagi 5.5 bilan o'rtacha)". **✅ Jurnalga yozish** bossangiz yoziladi, **❌ Bekor** bossangiz hech narsa o'zgarmaydi.

Mezonni o'zgartirish uchun GitHub'dagi `mezon.json` faylidagi raqamlarni tahrirlang, bot 10 daqiqada yangilanadi.
Boshqa kun uchun ovozda ayting: "kecha" yoki "25-oktabr".

## Ism topilmasa

Talaba topilmasa, jadvaldagi **"Kahoot taxalluslar"** varag'iga yozing: Guruh | Taxallus | Talaba (jurnaldagi to'liq ism). Keyingi safar o'zi topadi.

---

## O'rnatish (taxminan 40 daqiqa, bir marta)

### 1. Telegram bot

1. Telegram'da **@BotFather** → `/newbot` → nom bering. Bergan **token**ni saqlab qo'ying.
2. @BotFather → `/setprivacy` → botingizni tanlang → **Disable**. (Bot guruhdagi fayllarni ko'rishi uchun.)
3. Botni har bir fan guruhiga qo'shing.

### 2. GitHub

1. github.com → **New repository** → nomi `kahoot-jurnal-bot` → **Public** → Create.
   (Public bo'lishi xavfsiz: parol va tokenlar GitHub'ga yuklanmaydi, ular faqat serverda turadi.)
2. **Add file → Upload files** → shu papkadagi barcha fayllarni sudrab tashlang → **Commit changes**.

### 3. Google Cloud server (bepul e2-micro)

1. **console.cloud.google.com** ga jurnal turgan Gmail bilan kiring, Visa/Mastercard kartani ulang.
2. **Billing → Budgets & alerts → Create budget**: 1 dollar, ogohlantirish 50% va 100%. Biror narsa pullik bo'lib qolsa, darhol xat keladi.
3. O'ng yuqoridagi **Cloud Shell** (`>_`) tugmasini bosing va quyidagilarni ketma-ket nusxalab qo'ying:

```bash
gcloud services enable compute.googleapis.com sheets.googleapis.com

gcloud compute instances create kahoot-bot \
  --zone=us-central1-a --machine-type=e2-micro \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --scopes=https://www.googleapis.com/auth/spreadsheets

gcloud compute instances describe kahoot-bot --zone=us-central1-a \
  --format='value(serviceAccounts[0].email)'
```

4. Oxirgi buyruq `...-compute@developer.gserviceaccount.com` ko'rinishidagi manzil chiqaradi. **Baholash jurnalini** ochib, **Share** → shu manzilni **Editor** qilib qo'shing.

> Bepul bo'lishi uchun: faqat `us-central1`, `us-east1` yoki `us-west1` regioni, `e2-micro` va 30 GB `pd-standard` disk. Yuqoridagi buyruq aynan shunday.
> 90 kunlik sinov muddati tugaganda **"Activate full account"** ni bosing, aks holda server to'xtaydi. Bepul limit ichida pul yechilmaydi.

### 4. Botni serverga o'rnatish

Cloud Shell'da:

```bash
gcloud compute ssh kahoot-bot --zone=us-central1-a
```

Serverga kirgach (`FOYDALANUVCHI` o'rniga GitHub login'ingiz):

```bash
curl -fsSL https://raw.githubusercontent.com/FOYDALANUVCHI/kahoot-jurnal-bot/main/install.sh \
  | sudo bash -s https://github.com/FOYDALANUVCHI/kahoot-jurnal-bot.git
sudo nano /opt/kahoot-jurnal-bot/.env
```

`.env` faylga yozing: `TELEGRAM_TOKEN`, `SPREADSHEET_ID` (jurnal havolasidagi `/d/` dan keyingi qism), `GEMINI_API_KEY` (ixtiyoriy, aistudio.google.com/apikey). Saqlash: `Ctrl+O`, `Enter`, `Ctrl+X`.

```bash
sudo systemctl restart kahoot-bot
```

Botga Telegram'da shaxsiy `/start` yozing: u sizning **id** raqamingizni aytadi. Uni `.env` dagi `ADMIN_IDS=` ga yozib, yana `sudo systemctl restart kahoot-bot`.

### 5. Sinash

Fan guruhiga Kahoot Excel hisobotini tashlang. Bir necha soniyada faylga 👍 qo'yiladi va sizga hisobot keladi.

---

## Foydali buyruqlar (serverda)

```bash
sudo journalctl -u kahoot-bot -f      # bot jurnali (xatolarni ko'rish)
sudo systemctl restart kahoot-bot     # qayta ishga tushirish
sudo systemctl status kahoot-bot      # holati
```

GitHub'dagi kodni o'zgartirsangiz, server 10 daqiqa ichida yangilanib, botni o'zi qayta ishga tushiradi. Server o'chib-yonsa, bot ham o'zi ishga tushadi.
