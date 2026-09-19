# انتشار نسخه جدید WordSub (راهنمای فارسی)

دو خروجی می‌سازیم: **Setup.exe** (نصبی) و **portable ZIP** (پرتابل).
دو راه داری: دستی (روی لپ‌تاپ خودت) یا خودکار (گیت‌هاب اکشن).

## راه اول: دستی

### ۱. آماده‌سازی (فقط بار اول)

- نصب Python 3.11+ از python.org (تیک Add to PATH)
- نصب [Inno Setup 6](https://jrsoftware.org/isinfo.php)
- دانلود `ffmpeg-release-essentials.zip` از
  [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) و کپی این دو فایل به
  `assets\bin\`:
  - `ffmpeg.exe`
  - `ffprobe.exe`

### ۲. بیلد

```bat
cd C:\path\to\wordsub
pip install -r requirements.txt
pyinstaller wordsub-gui.spec
pyinstaller wordsub-cli.spec
```

خروجی در `dist\WordSub\` است. تست کن:

```bat
dist\WordSub\WordSub.exe
```

### ۳. پرتابل ZIP

```bat
powershell Compress-Archive -Path dist\WordSub\* -DestinationPath WordSub-portable-win64.zip
```

### ۴. نصاب Setup.exe

1. فایل `installer\wordsub.iss` را باز کن و `#define MyAppVersion` را
   با شماره نسخه جدید عوض کن (مثلا `1.1.0`).
2. در Inno Setup دکمه Compile را بزن (یا `ISCC.exe installer\wordsub.iss`).
3. خروجی در `release\WordSub-Setup-x.y.z.exe`.

### ۵. انتشار در گیت‌هاب

```bat
git tag v1.0.0
git push --tags
```

بعد در GitHub → Releases → Draft a new release → تگ را انتخاب کن و
دو فایل (`WordSub-Setup-*.exe` و `WordSub-portable-win64.zip`) را
آپلود کن.

## راه دوم: خودکار (توصیه برای بعد)

فقط تگ بزن و پوش کن — اکشن `release.yml` همه کارها را انجام می‌دهد
(ffmpeg را خودش دانلود می‌کند، هر دو بیلد را می‌سازد و Release می‌سازد):

```bat
git tag v1.0.0
git push --tags
```

## چک‌لیست قبل از انتشار

- [ ] شماره نسخه در `installer\wordsub.iss` به‌روز است
- [ ] `WordSub.exe` روی یک سیستم تمیز (بدون پایتون) باز و تست شده
- [ ] دانلود مدل + پیام VPN تست شده
- [ ] خروجی SRT روی یک ویدیو انگلیسی و یکی فارسی چک شده
