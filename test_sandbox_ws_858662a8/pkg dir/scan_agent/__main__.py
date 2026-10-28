"""نقطة الدخول: python -m scan_agent"""
import os
import sys
import time

from . import config


def attach_log_when_windowless():
    """تحت ``pythonw`` (اختصارُ بدء التشغيل) يكون ``sys.stdout`` و``sys.stderr`` ‏None:
    كلُّ print يضيع، وكلُّ ``sys.stderr.write`` يرمي AttributeError — فيسقط الإقلاعُ على
    منفذٍ مشغولٍ بلا أثر، ويسقط معالجُ الطلب قبل أن يكتب سطرَ الأصل المرفوض فتنقطع
    الاستجابة (ومسبارُ no-cors يقرأ الانقطاعَ «غيرَ مشغّل» لا «لا يثق بي»).
    فنوجّههما إلى agent.log: يصله كلُّ سطر، ومعه أثرُ أيّ استثناءٍ يُسقط الإقلاع."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    os.makedirs(config.data_dir(), exist_ok=True)
    log = open(config.log_file(), "a", encoding="utf-8", buffering=1)
    log.write("\n=== %s pid=%d ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    return log


if __name__ == "__main__":
    attach_log_when_windowless()
    from .server import serve       # بعد التوجيه: فشلُ الاستيراد نفسِه يصل إلى السجلّ
    serve()
