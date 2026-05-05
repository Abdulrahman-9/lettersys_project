#!/usr/bin/env python
"""
سكريبت لإدارة المستخدمين - حذف والمستخدمين القدماء وإضافة جديد
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys_core.settings')
django.setup()

from django.contrib.auth.models import User

def show_users():
    """عرض جميع المستخدمين"""
    users = User.objects.all()
    if not users:
        print("\n❌ لا توجد مستخدمين\n")
        return
    
    print("\n" + "="*50)
    print("👥 المستخدمين الحاليين:")
    print("="*50)
    for user in users:
        is_super = "✅ SuperUser" if user.is_superuser else "❌ عادي"
        print(f"  • {user.username:20} ({is_super})")
    print("="*50 + "\n")

def delete_user(username):
    """حذف مستخدم"""
    try:
        user = User.objects.get(username=username)
        user.delete()
        print(f"✅ تم حذف المستخدم: {username}\n")
        return True
    except User.DoesNotExist:
        print(f"❌ المستخدم '{username}' غير موجود\n")
        return False

def create_superuser(username, email, password):
    """إنشاء مستخدم جديد SuperUser"""
    try:
        if User.objects.filter(username=username).exists():
            print(f"❌ المستخدم '{username}' موجود بالفعل\n")
            return False
        
        user = User.objects.create_superuser(username, email, password)
        print(f"✅ تم إنشاء المستخدم: {username}\n")
        return True
    except Exception as e:
        print(f"❌ خطأ: {e}\n")
        return False

def main():
    """البرنامج الرئيسي"""
    print("\n" + "="*50)
    print("🔐 إدارة المستخدمين - Lettersys")
    print("="*50 + "\n")
    
    while True:
        print("📋 الخيارات:")
        print("  1️⃣  عرض المستخدمين")
        print("  2️⃣  حذف مستخدم")
        print("  3️⃣  إضافة مستخدم جديد")
        print("  4️⃣  حذف جميع المستخدمين وإضافة جديد")
        print("  5️⃣  خروج")
        print()
        
        choice = input("اختر (1-5): ").strip()
        
        if choice == "1":
            show_users()
        
        elif choice == "2":
            username = input("اسم المستخدم المراد حذفه: ").strip()
            if username:
                delete_user(username)
            show_users()
        
        elif choice == "3":
            username = input("اسم المستخدم الجديد: ").strip()
            email = input("البريد الإلكتروني: ").strip()
            password = input("كلمة المرور: ").strip()
            
            if username and email and password:
                create_superuser(username, email, password)
            show_users()
        
        elif choice == "4":
            confirm = input("هل أنت متأكد؟ سيتم حذف جميع المستخدمين (y/n): ").strip().lower()
            if confirm == 'y':
                users = User.objects.all()
                count = users.count()
                users.delete()
                print(f"✅ تم حذف {count} مستخدم\n")
                
                username = input("اسم المستخدم الجديد: ").strip()
                email = input("البريد الإلكتروني: ").strip()
                password = input("كلمة المرور: ").strip()
                
                if username and email and password:
                    create_superuser(username, email, password)
            show_users()
        
        elif choice == "5":
            print("👋 وداعاً!\n")
            break
        
        else:
            print("❌ اختيار غير صحيح\n")

if __name__ == "__main__":
    main()
