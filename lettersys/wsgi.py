import os
# حدّ خيوط OpenBLAS/OMP قبل استيراد numpy/scipy/sklearn — يمنع OOM على 8GB.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

# إحماءُ الاستخراج في الخلفيّة — هنا لا في AppConfig.ready: عمليّاتُ الخدمة وحدها تستورد
# هذا الملفّ، فلا يجري أثناء migrate أو الاختبارات.
from core.extraction.warmup import start_extraction_warmup  # noqa: E402
start_extraction_warmup()
