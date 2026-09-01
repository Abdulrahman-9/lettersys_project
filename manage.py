#!/usr/bin/env python
import os
import sys

# حدّ خيوط OpenBLAS/OMP (numpy/scipy/sklearn) قبل أيّ استيراد لها — يمنع استنزاف
# الذاكرة (OOM) على الأجهزة المحدودة (8GB). setdefault يحترم أيّ تجاوز صريح.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
