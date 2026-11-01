# NibrasLite — مكتبة مساعدة خفيفة لسيلينيوم بواجهة عربية

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Selenium](https://img.shields.io/badge/Selenium-4.48%2B-43B02A.svg)
![Platform](https://img.shields.io/badge/Platform-Windows_%7C_macOS_%7C_Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

مكتبة بايثون خفيفة تربط كودك بمتصفح Chrome **مستقر ودائم** — النافذة لا تُغلق عند انتهاء السكربت.
تستورد واجهة السيلينيوم كاملة من مكان واحد، مع نظام بروفايلات، حقن كوكيز، كشف ذاتي، ودعم بروكسي متعدد الأنواع.

---

## ✨ الميزات

| الميزة | الوصف |
|--------|-------|
| 🔄 **جلسة دائمة** | شغّل Chrome مرة واحدة، عدّ السكربتات وتبقى النافذة والتبويبات والكوكيز حيّة |
| 🐍 **واجهة سيلينيوم كاملة** | `By` · `Keys` · `Select` · `ActionChains` · `WebDriverWait` · `EC` + كل الاستثناءات |
| 🎭 **Stealth مدمج** | إخفاء آثار الأتمتة بـ JavaScript خاص — بلا أي مكتبة ثالثة |
| 📁 **نظام بروفايلات** | بروفايل دائم افتراضي · بروفايلات مسمّاة · بروفايلات مؤقتة تُحذف تلقائياُ |
| 🍪 **حقن الكوكيز** | `browser.cookies_load()` → `browser.inject(driver, cookies)` |
| 🌐 **بروكسي متعدد** | `proxy_http` · `proxy_https` · `proxy_socks4` · `proxy_socks5` + دالة `proxy_check` |
| 🖥️ **CLI جاهز** | أوامر `start` · `attach` · `stop` · `status` · `profiles` مباشرة من التيرمينال |
| 🧪 **فحص ذاتي 20/20** | اختبارات شاملة لكل ميزة للتأكد من عدم regressions |
| 🪟 **متعدد المنصات** | يعمل على Windows / macOS / Linux (يكشف Chrome تلقائياُ) |

---

## 📦 التثبيت

### عبر pip (موصى به)

```bash
pip install nibraslite
```

### من المصدر

```bash
pip install selenium>=4.48
# تأكد من وجود Chrome أو Chromium مُثبّت على جهازك
```

المكتبة تعتمد على Selenium فقط — لا تحتاج تثبيت حزم إضافية.

---

## 🚀 الاستخدام السريع

### 1. تشغيل المتصفح والبدء

```python
from nibraslite import browser
from selenium.webdriver.common.by import By

# بدء جلسة دائمة + stealth في سطر واحد
driver = browser.ensure("https://example.com")

# استخدام كامل واجهة السيلينيوم
driver.find_element(By.NAME, "q").send_keys("nibras")
driver.find_element(By.NAME, "q").submit()
```

### 2. الـ REPL التفاعلي

```bash
python browser.py start
python browser.py attach          # فتح REPL متصل بالنافذة الحالية
```

### 3. سكريبت مستقل

```python
from nibraslite import browser
from selenium.webdriver.common.by import By

driver = browser.attach()         # الربط بنافذة شغّالة (لا تبدأ واحدة جديدة)
browser.stealth(driver)           # تفعيل إخفاء الأتمتة
driver.get("https://example.com")
```

### 4. مثال كامل مع كوكيز

```python
from nibraslite import browser
import json
from pathlib import Path

driver = browser.ensure(apply_stealth=True)
browser.goto(driver, "https://accounts.google.com")

cookies = json.loads(Path("session_cookies.json").read_text(encoding="utf-8"))
ok, failed = browser.inject(driver, cookies)
print(f"✅ {ok} كوكيز حقّنت | ❌ {failed} فشلت")
```

---

## 📁 هيكل الملفات

```
sel_nibras/
├── browser.py          # ❤️ قلب المكتبة — دورة الحياة + stealth + كوكيز + عناصر + CLI
├── selfcheck.py        # 20 فحص ذاتي يغطي كل الميزات
├── test.py             # سكربت Crashlytics أحادي الاستخدام
├── example.py          # نموذج استخدام عام لأي موقع
├── probe.py            # فاحص سريع لأي صفحة (DOM + stealth report)
├── convert_cookies.py  # يحوّل لصق DevTools → JSON قابل للحقن
├── browser_guide.html  # دليل عربي بصري للمستخدم
└── README.md           # هذا الملف
```

---

## ⌨️ أوامر CLI

```bash
python browser.py start [--url URL] [--name NAME] [--temp] [--port N] [--ua "USER-AGENT"]
python browser.py attach  [--name NAME] [--port N]
python browser.py status  [--all]
python browser.py stop    [--name NAME] [--port N] [--all] [--keep]
python browser.py profiles
python browser.py profile new <name>
python browser.py profile rm  <name> [-y]
python selfcheck.py                    # تشغيل الفحص الذاتي
```

---

## 🔧 المتغيرات البيئية

| المتغيّر | القيمة الافتراضية | الوصف |
|----------|-------------------|-------|
| `NIBRAS_PORT` | `9222` | منفذ Debug للربط |
| `NIBRAS_PROFILE` | `_profile/` | مسار البروفايل الدائم |
| `NIBRAS_UA` | — | تجاوز User-Agent |
| `NIBRAS_HEADLESS` | `0` | `1` = وضع بدون واجهة |
| `NIBRAS_CHROME` | — | مسار Chrome.exe صريح |

---

## 🛡️ Stealth — الإخفاء المدمج

لا نستخدم أي مكتبة خارجية. الـ stealth مبني بـ JavaScript يُحقَن في كل تبويبة:

```javascript
// ما يخفيه STEALTH_JS:
navigator.webdriver = false
navigator.languages = [...]       // حسب locale الحقيقي
navigator.hardwareConcurrency   // مطابق لجهاز المستخدم
window.chrome.runtime          // موجود كمتصفح حقيقي
WebGL vendor/renderer          // مخفي (بدون SwiftShader)
permissions.query(notifications) // لا يعيد "denied"
```

> ⚠️ **تنويه**: هذا Stealth **خفيف** ومخصص للمواقع البسيطة. لا يغطي أنظمة الكشف المتقدمة
> مثل Google reCAPTCHA v3 أو Cloudflare Turnstile. للمواقع الحساسة استخدم أدوات متخصصة.

---

## 📊 نظام البروفايلات

| النوع | المسار | يبقى بعد الإيقاف؟ | طريقة الاستخدام |
|-------|--------|:------------------:|----------------|
| **افتراضي** | `_profile/` | ✅ نعم | `browser.py start` |
| **مسمّى** | `profiles/<name>/` | ✅ نعم | `browser.py start --name work` |
| **مسار صريح** | أي مسار تختاره | ✅ نعم | `browser.py start --profile /path/to/dir` |
| **مؤقت** | OS temp dir | ❌ لا (إلا `--keep`) | `browser.py start --temp` |



لتشغيل حسابين في وقت واحد: `--name a` و `--name b` — المكتبة تختار منافذ حرة تلقائياُ.

---

## 🖥️ تشغيل عدة متصفحات مستقلة

تفتح أكثر من نافذة Chrome في نفس الوقت، كل واحدة بـ بروفايل مستقل (تسجيل دخول منفصل).

### بروفايلات مسمّاة (تسجيل دخول محفوظ)

```python
from nibraslite import browser

# متصفح #1 — حساب Work
browser.start(name="work")
driver_work = browser.attach(name="work")
driver_work.get("https://gmail.com")

# متصفح #2 — حساب Personal (منفذ مختلف تلقائياُ)
browser.start(name="personal")
driver_personal = browser.attach(name="personal")
driver_personal.get("https://gmail.com")

# كل driver يعمل بشكل مستقل تماماُ
```

### بروفايلات مؤقتة (جلسة نظيفة كل مرة)

```python
from nibraslite import browser

port1 = browser.start(temp=True)
driver1 = browser.attach(port=port1)

port2 = browser.start(temp=True)
driver2 = browser.attach(port=port2)
```

### عرض الحالات

```python
# كل النسخ الشغّالة
print(browser.running_instances())
# [(9222, '/.../profiles/work'), (9223, '/.../profiles/personal')]

# البروفايلات الدائمة
print(browser.list_profiles())
# [('work', 12345), ('personal', 67890)]
```

> **ملاحظة:** عند استدعاء `start()` بدون أي معاملات تعيد استخدام النسخة الموجودة.
> لفتح متصفح جديد يجب تمرير `name=...` أو `temp=True` أو `port=...`.
> عندما لا تمرر `profile=` يكون `temp=True` افتراضيًا (نافذة نظيفة كل مرة).
> عندما تمرر `profile=...` يكون `temp=False` (بروفايل دائم محفوظ).

---

## 🔗 تدفّق الكوكيز

```
[متصفح آخر] → DevTools → Console → copy table
      ↓
new_coc.txt
      ↓
python convert_cookies.py
      ↓
session_cookies.json
      ↓
browser.inject(driver, cookies)
```

الدالة `inject` تستخدم CDP `Network.setCookie` وتدعم `__Host-*` و `SameSite`.

---

## 📈 قائمة الـ APIs العامة

### دورة الحياة
```python
browser.start(...)        → port      # تشغيل Chrome مستقل
browser.attach(...)       → driver    # ربط بنافذة شغّالة
browser.ensure(url, ...)  → driver    # الكل في واحد (start + attach + stealth)
browser.kill(...)                 # إيقاف Chrome الخاص بنا فقط
browser.is_alive(port)    → bool
browser.close_browser(driver)     # إغلاق النافذة كلها
```

### البروفايلات
```python
browser.list_profiles()               → list[(name, size_bytes)]
browser.delete_profile(name, yes=False)
browser.running_instances()           → list[(port, profile)]
browser.find_port(name=None)          → int | None
browser.next_free_port()              → int
```

### الكوكيز
```python
browser.cookies_load(path)            → list[dict]
browser.cookies_save(driver, path)
browser.inject(driver, cookies)       → (ok_count, fail_count)
browser.clear(driver, domain=None)
browser.list_cookies(driver)
browser.from_devtools_table(text)     → list[dict]
```

### الـ Stealth
```python
browser.stealth(driver, all_tabs=True)
browser.check_stealth(driver)         → dict{raw, tests, passed}
browser.print_stealth(driver)         → bool
```

### العناصر والانتظار
```python
browser.wait(driver, sel, state, timeout=20)   → WebElement
browser.wait_all(driver, sel, timeout=20)      → list[WebElement]
browser.wait_gone(driver, sel, timeout=20)     → bool
browser.exist / visible / clickable(driver, sel, timeout=0) → bool
browser.one(driver, sel, timeout=0)            → WebElement | None
browser.find(driver, sel)                      → list[WebElement]
```

### الأحداث
```python
browser.goto / click / clickn / type_text / body_text / dump
browser.eval_js / scroll / screenshot / tabs / new_tab / switch_tab / accept_alert
```

### البروكسي
```python
browser.proxy_check("1.2.3.4", 8080, user="u", pass="p") → dict
browser.proxy_http / proxy_https / proxy_socks4 / proxy_socks5
browser.proxy_combine("socks5", "addr", port)
```

### كائن Browser (الواجهة الشاملة)
```python
from nibraslite import Browser, By
b = Browser.ensure("https://example.com")
b.find_element(By.ID, "q")       # → دالة سيلينيوم أصلية (marshaled تلقائياُ)
b.click("#go")                   # → دالة مكتبتنا
b.wait("#t", "visible", 5)       # → دالة مكتبتنا
b.driver                         # → WebDriver الخام
```

---

## 🧪 التشغيل

```bash
# تشغيل الفحص الذاتي الكامل
python selfcheck.py

# تشغيل مثال عام
python example.py

# فحص صفحة محددة
python probe.py
```

---

## 🤝 المساهمة

1. اقرأ [README.md](README.md) (هذا الملف) قبل أي تعديل
2. أضف الدالة الجديدة في `browser.py`
3. أضف اختباراُ في `selfcheck.py`
4. حدّث هذا الملف
5. اختبر: `python selfcheck.py`

---

## 📜 الرخصة

MIT — حرية الاستخدام والتعديل والتوزيع.
