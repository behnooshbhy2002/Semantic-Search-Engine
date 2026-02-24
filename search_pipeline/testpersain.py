from bidi.algorithm import get_display
import arabic_reshaper

# تابع برای اصلاح متن فارسی
def process_farsi_text(text):
    reshaped_text = arabic_reshaper.reshape(text)  # اتصال حروف
    return get_display(reshaped_text)  # راست‌چین کردن متن
