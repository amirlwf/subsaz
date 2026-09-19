<p align="center">
  <img src="logo/with-background.png" width="280" alt="ساب‌ساز">
</p>

<h1 align="center">ساب‌ساز — زیرنویس دقیق کلمه‌به‌کلمه، آفلاین</h1>

<p align="center">
  فایل ویدیو یا صوت بده، فایل <code>srt</code> دقیق بگیر.
  رونویسی کاملاً لوکال با <code>faster-whisper</code> — بدون API و بدون آپلود.
</p>

<p align="center">
  <a href="README.md">⬅ بازگشت</a>
  &nbsp;•&nbsp;
  <a href="README_EN.md">English guide</a>
</p>

## ⬇ دانلود

از صفحه [Releases](https://github.com/amirlwf/subsaz/releases):

| فایل | چیه |
|---|---|
| `SubSaz-Setup-x.y.z.exe` | نصاب ویندوز (شورتکات منوی استارت و دسکتاپ + آن‌اینستالر) |
| `SubSaz-portable-win64.zip` | پرتابل — زیپ را باز کن و `SubSaz.exe` را اجرا کن، بدون نصب |

> 🇮🇷 اگر دانلود مدل ناموفق بود، به VPN وصل شو و دوباره تلاش کن —
> مدل‌ها روی HuggingFace هستند که تحریم است. خود برنامه هم این را می‌گوید.

## 🚀 اولین اجرا (۲ دقیقه)

1. ساب‌ساز را باز کن.
2. **بخش ۲ (سیستم و مدل)** را ببین: برنامه سیستمت را اسکن می‌کند
   (CPU / رم / کارت NVIDIA) و بهترین مدل را پیشنهاد می‌دهد.
3. **⬇ دانلود مدل** را بزن و تایید کن — فقط یک‌بار، بعدش کاملاً آفلاین.
4. فایل اضافه کن → استایل زیرنویس را انتخاب کن → **▶ ساخت زیرنویس (SRT)**.

## 🤖 انتخاب خودکار مدل

| سیستم تو | انگلیسی | فارسی | موتور |
|---|---|---|---|
| گرافیک NVIDIA با ۸GB+ VRAM | `large-v3-turbo` | `large-v3-turbo` | `float16` |
| گرافیک NVIDIA با ۴ تا ۸GB | `small` | `large-v3-turbo` | `float16` |
| CPU قوی (۸+ ترد / ۱۶GB+ رم) | `small` | `large-v3-turbo` | `int8` |
| CPU ضعیف | `small` | اول `base` سریع، اگر اطمینان کم بود خودکار `turbo` | `int8` |

سیستم ضعیف همان دقت را می‌گیرد، فقط کندتر. فارسی همیشه دقیق‌ترین مدل را می‌گیرد
و انگلیسی از نقطه بهینه `small` استفاده می‌کند.
می‌توانی مدل را دستی هم قفل کنی (`auto` = انتخاب خودکار سخت‌افزاری).

از ترمینال هم می‌توانی چک کنی:

```bat
subsaz-cli --scan
```

## ✨ استایل‌های زیرنویس

- **single** — تک‌خطی (استایل کلاسیک شورت و تیک‌تاک)
- **two** — حداکثر دوخطی، به سبک ادوبی پریمیر
- **کلمه در خط** (۱ تا ۶)، **حداکثر حروف در خط** (۲۰ تا ۵۰)
- **گپ** (ثانیه) که خط را می‌شکند، **مکث** (ثانیه) که خط را تا شروع خط بعدی
  نگه می‌دارد (بدون چشمک‌زدن)
- **کلمات خاص** — اسم برند و اصطلاحات تخصصی درست رونویسی می‌شوند

خط‌ها اول روی نقطه‌گذاری جمله می‌شکنند، بعد روی سقف حروف — هیچ‌وقت وسط کلمه.

## 🎞 فرمت‌ها

ویدیو: `mp4 mov mkv webm ts flv wmv avi m4v mpg mpeg 3gp 3g2`
صوت: `mp3 wav m4a aac flac ogg opus wma`

## ⌨ خط فرمان (CLI)

```bat
subsaz-cli video.mp4 --lang en
subsaz-cli video.mp4 --lang fa --mode two --max-chars 36
subsaz-cli song.mp3 --lang en --words 2
subsaz-cli --dir C:\clips --lang en
subsaz-cli --scan
subsaz-cli --download-model small
```

## 🎯 جزئیات دقت

- تایم‌استمپ در سطح کلمه (`word_timestamps=True`، همراه VAD)
- گروه‌بندی حساس به نقطه‌گذاری + سقف حروف + ادغام خط‌های تک‌افتاده
- `condition_on_previous_text=False` (بدون توهم روی موزیک و نویز)
- نرمالایزر فارسی (حروف عربی→فارسی، لغزش‌های رایج ASR)
- اجرای مجدد اطمینانی: اول مدل سریع رونویسی می‌کند؛ اگر اطمینان کم بود،
  مدل دقیق خودکار دوباره اجرا می‌شود

## 🛠 اجرا از سورس (توسعه‌دهنده‌ها)

```bat
pip install -r requirements.txt
python gui.py
```

به Python 3.11+ و `ffmpeg`/`ffprobe` در PATH نیاز داری
(نسخه بسته‌بندی‌شده خودش دارد — فقط اجرای سورس این را می‌خواهد).

## 🗂 ساختار پروژه

```
app/hardware.py       اسکن سیستم + پیشنهاد مدل
app/model_manager.py  دانلود یک‌باره، ادامه‌نیمه‌کاره، راهنمای VPN
app/transcribe.py     خط لوله مدیا ← کلمات
app/subtitles.py      سازنده SRT تک‌خطی / دوخطی
app/config.py         تنظیمات ماندگار (%LOCALAPPDATA%/SubSaz)
gui.py                اپ دسکتاپ (CustomTkinter)
cli.py                رابط ترمینال (همان موتور)
installer/subsaz.iss  اسکریپت Inno Setup
```

## ⚖ لایسنس

MIT — فایل [LICENSE](LICENSE) را ببین. فونت: [وزیرمتن](https://github.com/rastikerdar/vazirmatn) (OFL).
