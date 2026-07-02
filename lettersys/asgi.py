import os
# حدّ خيوط OpenBLAS/OMP قبل استيراد numpy/scipy/sklearn — يمنع OOM على 8GB.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
from django.core.asgi import get_asgi_application
application = get_asgi_application()
