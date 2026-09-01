# 📚 API Reference - نظام الاستخراج الذكي

**الإصدار:** 1.0.0  
**آخر تحديث:** 22 يناير 2026  
**الحالة:** Production Ready

---

## 🔐 المصادقة (Authentication)

جميع APIs تتطلب تسجيل دخول:

```bash
# الطلب يجب أن يتضمن:
- Cookie: sessionid=<session_id>
- Header: X-CSRFToken=<csrf_token>
```

---

## 📡 الـ Endpoints

### 1️⃣ بدء الاستخراج

```http
POST /api/extract/
Content-Type: multipart/form-data
```

**المعاملات:**
```json
{
  "file": "<binary_file>"  // الملف المراد استخراج البيانات منه
}
```

**الاستجابة (نجاح):**
```json
{
  "success": true,
  "extraction_id": 123,
  "confidence": 0.87,
  "status": "processing",
  "message": "تم بدء الاستخراج"
}
```

**الاستجابة (خطأ):**
```json
{
  "success": false,
  "error": "نوع الملف غير مدعوم",
  "status_code": 400
}
```

**الأكواد:**
- `200`: نجح
- `400`: خطأ في الملف
- `403`: غير مصرح
- `429`: تجاوز الحد الأقصى

---

### 2️⃣ جلب النتائج

```http
GET /api/extract/<attachment_id>/
```

**المعاملات:**
- `attachment_id` (integer): معرّف المرفق

**الاستجابة:**
```json
{
  "id": 123,
  "attachment_id": 456,
  "status": "completed",
  "created_at": "2026-01-22T10:30:00Z",
  "updated_at": "2026-01-22T10:31:00Z",
  
  "book_number": "2024-001",
  "book_number_confidence": 0.95,
  
  "title": "اسم المستند",
  "title_confidence": 0.87,
  
  "book_date": "2024-01-15",
  "book_date_confidence": 0.92,
  
  "secret_level": "سري",
  "secret_level_confidence": 0.88,
  
  "book_kind": "incoming",
  "book_kind_confidence": 0.91,
  
  "issuing_entity_id": null,
  "receiving_entity_id": null,
  
  "overall_confidence": 0.90,
  "margin_text": null,
  
  "reviewed_by": null,
  "reviewed_at": null,
  "approved_by": null,
  "approved_at": null
}
```

**الأكواد:**
- `200`: نجح
- `404`: لم يتم العثور عليه

---

### 3️⃣ إرسال التصحيحات

```http
POST /api/extract/<extraction_id>/feedback/
Content-Type: application/json
```

**المعاملات:**
```json
{
  "field_name": "title",           // اسم الحقل المصحح
  "original_value": "عنوان خاطئ",   // القيمة الأصلية
  "corrected_value": "عنوان صحيح",  // القيمة المصححة
  "reason": "تصحيح يدوي"            // سبب التصحيح
}
```

**الاستجابة:**
```json
{
  "status": "ok",
  "message": "تم حفظ التصحيح",
  "feedback_id": 789,
  "learning_impact": "positive"
}
```

---

### 4️⃣ المراجعة والاعتماد

```http
POST /api/extract/<extraction_id>/review/
Content-Type: application/json
```

**المعاملات:**
```json
{
  "action": "approve",             // approve أو reject
  "notes": "الملاحظات إن وجدت",
  "reviewer_notes": "ملاحظات المراجع",
  "corrections": {                 // تصحيحات اختيارية
    "title": "العنوان المصحح",
    "book_number": "2024-002"
  }
}
```

**الاستجابة:**
```json
{
  "status": "ok",
  "message": "تمت المراجعة بنجاح",
  "extraction_id": 123,
  "action": "approved",
  "reviewed_at": "2026-01-22T10:35:00Z"
}
```

---

### 5️⃣ الإحصائيات

```http
GET /api/extract/statistics/
```

**معاملات الاستعلام (Query Parameters):**
- `days` (integer, اختياري): عدد الأيام الماضية (افتراضي: 7)
- `field` (string, اختياري): حقل محدد

**الاستجابة:**
```json
{
  "period": "7 أيام",
  "total_extractions": 45,
  "successful": 38,
  "failed": 7,
  "success_rate": 84.4,
  "average_confidence": 0.86,
  
  "by_field": {
    "book_number": {
      "total": 45,
      "accuracy": 0.95,
      "average_confidence": 0.92
    },
    "title": {
      "total": 45,
      "accuracy": 0.82,
      "average_confidence": 0.87
    }
  },
  
  "by_day": {
    "2026-01-22": {
      "total": 12,
      "success": 10,
      "rate": 83.3
    }
  },
  
  "trends": {
    "improving": true,
    "change_percent": 5.2
  }
}
```

---

## 📊 نماذج البيانات

### DataExtractionResult
```python
{
  "id": int,                          # معرّف فريد
  "attachment": Attachment,           # المرفق المرتبط
  "status": "pending|processing|completed|failed",
  
  # البيانات المستخرجة
  "book_number": str,
  "title": str,
  "book_date": date,
  "secret_level": str,
  "book_kind": str,
  "margin_text": str,
  
  # درجات الثقة (0.0 - 1.0)
  "book_number_confidence": float,
  "title_confidence": float,
  "book_date_confidence": float,
  "secret_level_confidence": float,
  "book_kind_confidence": float,
  "overall_confidence": float,
  
  # المراجعة والاعتماد
  "reviewed_by": User,
  "reviewed_at": datetime,
  "approved_by": User,
  "approved_at": datetime,
  "book": Book,
  
  # البيانات الوصفية
  "created_at": datetime,
  "updated_at": datetime,
  "created_by": User
}
```

### ExtractionFeedback
```python
{
  "id": int,
  "extraction": DataExtractionResult,
  "field_name": str,                  # اسم الحقل
  "feedback_type": "incorrect|partial|missing",
  "original_value": str,
  "corrected_value": str,
  "reason": str,
  "is_error": bool,                   # هل كان هناك خطأ
  "created_by": User,
  "created_at": datetime
}
```

---

## 🎯 رموز الخطأ

| الكود | المعنى | الحل |
|------|-------|-----|
| 400 | طلب غير صحيح | تحقق من البيانات المرسلة |
| 401 | غير مصرح | تسجيل الدخول مطلوب |
| 403 | محظور | ليس لديك صلاحيات |
| 404 | لم يُعثر عليه | تحقق من المعرّف |
| 429 | تجاوز الحد | انتظر وحاول لاحقاً |
| 500 | خطأ في الخادم | اتصل بالدعم |

---

## 📝 أمثلة مكتملة

### مثال 1: استخراج من البداية للنهاية

```bash
#!/bin/bash

# 1. بدء الاستخراج
EXTRACT_RESPONSE=$(curl -X POST \
  -H "X-CSRFToken: $CSRF_TOKEN" \
  -F "file=@document.jpg" \
  -b "sessionid=$SESSION_ID" \
  http://localhost:8000/api/extract/)

EXTRACTION_ID=$(echo $EXTRACT_RESPONSE | jq '.extraction_id')

# 2. انتظر المعالجة (30 ثانية)
sleep 30

# 3. جلب النتائج
RESULTS=$(curl -X GET \
  -b "sessionid=$SESSION_ID" \
  http://localhost:8000/api/extract/$EXTRACTION_ID/)

# 4. إذا كان هناك خطأ، صحح
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{
    "field_name": "title",
    "corrected_value": "العنوان الصحيح"
  }' \
  -b "sessionid=$SESSION_ID" \
  http://localhost:8000/api/extract/$EXTRACTION_ID/feedback/

# 5. اعتمد النتائج
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"action": "approve"}' \
  -b "sessionid=$SESSION_ID" \
  http://localhost:8000/api/extract/$EXTRACTION_ID/review/
```

### مثال 2: JavaScript

```javascript
// 1. رفع الملف
async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch('/api/extract/', {
    method: 'POST',
    body: formData,
    headers: {
      'X-CSRFToken': getCookie('csrftoken')
    }
  });
  
  return await response.json();
}

// 2. الحصول على النتائج
async function getResults(extractionId) {
  const response = await fetch(`/api/extract/${extractionId}/`);
  return await response.json();
}

// 3. تصحيح
async function submitCorrection(extractionId, field, value) {
  const response = await fetch(`/api/extract/${extractionId}/feedback/`, {
    method: 'POST',
    body: JSON.stringify({
      field_name: field,
      corrected_value: value,
      reason: 'تصحيح يدوي'
    }),
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken')
    }
  });
  
  return await response.json();
}
```

---

## ⚙️ معدلات التحديد (Rate Limiting)

- **للسكانر:** 3 محاولات كل 5 دقائق
- **للمستخدمين العاديين:** لا حد
- **للمشرفين:** لا حد

---

## 📊 نصائح الأداء

1. **استخدم الـ IDs بدل البحث**
   ```javascript
   // ✓ صحيح
   GET /api/extract/123/
   
   // ✗ بطيء
   GET /api/extract/?file_name=document.jpg
   ```

2. **اجمع الطلبات**
   ```javascript
   // ✓ أفضل
   POST /api/extract/123/feedback/  // طلب واحد
   
   // ✗ بطيء
   POST /api/extract/123/feedback/   // عدة طلبات
   POST /api/extract/123/review/
   ```

3. **استخدم الـ Cache**
   ```javascript
   const cache = new Map();
   if (cache.has(id)) return cache.get(id);
   ```

---

## 🔔 الأحداث (Events)

تُرسل الطلبات الآلية عند:
- إكمال الاستخراج
- حفظ التصحيح
- اعتماد النتيجة

---

## 📞 الدعم والمساعدة

- **الأخطاء:** تحقق من السجلات في Django console
- **الأسئلة:** راجع [EXTRACTION_GUIDE.md](EXTRACTION_GUIDE.md)
- **الميزات الجديدة:** أرسل طلب تحسين
