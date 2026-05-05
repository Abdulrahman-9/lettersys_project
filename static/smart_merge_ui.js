/**
 * واجهة محسّنة لدمج الملفات الذكية
 * 3 أزرار: حذف، دمج، إضافة
 */

const SmartMergeUI = {
    currentAttachmentId: null,
    currentFileUrl: null,
    currentFileName: null,
    mergeModalEl: null,
    isProcessing: false,

    /**
     * تهيئة الواجهة
     */
    init: function() {
        this.attachEventListeners();
        this.createMergeModal();
    },

    notify: function(message, type, title) {
        if (window.ToastCenter && typeof window.ToastCenter.show === 'function') {
            window.ToastCenter.show(type || 'info', message, {
                title: title || 'معلومة',
                delay: (type || 'info') === 'error' ? 6500 : 4000,
            });
            return;
        }

        alert(message);
    },

    /**
     * إنشاء modal للدمج الذكي
     */
    createMergeModal: function() {
        const html = `
            <div class="modal fade" id="smartMergeModal" tabindex="-1" role="dialog" aria-hidden="true">
                <div class="modal-dialog modal-lg" role="document">
                    <div class="modal-content">
                        <!-- رأس الـ Modal -->
                        <div class="modal-header border-bottom">
                            <h5 class="modal-title">
                                <i class="bi bi-gear"></i> إدارة الملف الذكية
                            </h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>

                        <!-- محتوى الـ Modal -->
                        <div class="modal-body">
                            <!-- عرض معلومات الملف الحالي -->
                            <div class="alert alert-info">
                                <strong>الملف الحالي:</strong> <span id="currentFileName"></span>
                            </div>

                            <!-- رسائل التقدم والأخطاء -->
                            <div id="mergeMessage" class="alert alert-dismissible fade" role="alert" style="display:none;">
                                <span id="mergeMessageText"></span>
                                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>

                            <!-- Progress Bar -->
                            <div id="mergeProgress" class="progress" style="display:none; height: 20px;">
                                <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated" 
                                     role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">
                                    جاري المعالجة...
                                </div>
                            </div>

                            <!-- قسم اختيار نوع العملية -->
                            <div class="mt-4">
                                <h6 class="border-bottom pb-2">اختر الإجراء المطلوب:</h6>
                                
                                <!-- أزرار الإجراءات الثلاثة -->
                                <div class="row mt-3">
                                    <!-- زر حذف -->
                                    <div class="col-md-4">
                                        <button class="btn btn-danger btn-block merge-action-btn" data-action="delete">
                                            <i class="bi bi-trash"></i>
                                            <br/>
                                            <small>حذف الملف</small>
                                        </button>
                                    </div>

                                    <!-- زر دمج -->
                                    <div class="col-md-4">
                                        <button class="btn btn-warning btn-block merge-action-btn" data-action="merge">
                                            <i class="bi bi-shuffle"></i>
                                            <br/>
                                            <small>دمج ملف</small>
                                        </button>
                                    </div>

                                    <!-- زر إضافة -->
                                    <div class="col-md-4">
                                        <button class="btn btn-success btn-block merge-action-btn" data-action="upload">
                                            <i class="bi bi-plus-circle"></i>
                                            <br/>
                                            <small>إضافة ملف</small>
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- قسم إدخال الملفات (hidden بشكل افتراضي) -->
                            <div id="fileInputSection" style="display:none; margin-top: 20px;">
                                <div class="card">
                                    <div class="card-body">
                                        <h6 class="card-title">اختر الملف الجديد</h6>
                                        <div class="custom-file">
                                            <input type="file" class="custom-file-input" id="mergeFileInput" accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp">
                                            <label class="custom-file-label" for="mergeFileInput">اختر ملف...</label>
                                        </div>
                                        <small class="form-text text-muted mt-2">
                                            أنواع مدعومة: PDF, JPEG, PNG, GIF, BMP, WebP
                                        </small>
                                    </div>
                                </div>
                            </div>

                            <!-- قسم التأكيد على الحذف (hidden بشكل افتراضي) -->
                            <div id="deleteConfirmSection" style="display:none; margin-top: 20px;">
                                <div class="alert alert-danger">
                                    <strong>تنبيه!</strong> هل تريد حذف هذا الملف؟
                                    <div class="mt-2">
                                        <label>سبب الحذف (اختياري):</label>
                                        <textarea id="deleteReason" class="form-control form-control-sm" rows="2" placeholder="مثال: ملف خاطئ، نسخة قديمة..."></textarea>
                                    </div>
                                </div>
                            </div>

                            <!-- قسم اختيار نوع الدمج -->
                            <div id="mergeTypeSection" style="display:none; margin-top: 20px;">
                                <div class="card">
                                    <div class="card-body">
                                        <h6 class="card-title">نوع الدمج</h6>
                                        <div class="custom-control custom-radio">
                                            <input type="radio" class="custom-control-input" id="mergeTypeSmart" 
                                                   name="mergeType" value="smart" checked>
                                            <label class="custom-control-label" for="mergeTypeSmart">
                                                <strong>تلقائي (موصى به)</strong> - اكتشاف نوع الملفات تلقائياً
                                            </label>
                                        </div>
                                        <div class="custom-control custom-radio">
                                            <input type="radio" class="custom-control-input" id="mergeTypePDF" 
                                                   name="mergeType" value="pdf">
                                            <label class="custom-control-label" for="mergeTypePDF">
                                                دمج PDF - دمج الصفحات
                                            </label>
                                        </div>
                                        <div class="custom-control custom-radio">
                                            <input type="radio" class="custom-control-input" id="mergeTypeImage" 
                                                   name="mergeType" value="image">
                                            <label class="custom-control-label" for="mergeTypeImage">
                                                دمج الصور - دمج عمودي
                                            </label>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- قسم سجل الإصدارات -->
                            <div id="versionsSection" style="margin-top: 20px;">
                                <h6 class="border-bottom pb-2">سجل الإصدارات</h6>
                                <div id="versionsList" style="max-height: 250px; overflow-y: auto;"></div>
                            </div>
                        </div>

                        <!-- أسفل الـ Modal -->
                        <div class="modal-footer border-top">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">إغلاق</button>
                            <button id="executeActionBtn" type="button" class="btn btn-primary" style="display:none;">
                                تنفيذ العملية
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
        this.mergeModalEl = document.getElementById('smartMergeModal');
        this.attachModalEventListeners();
    },

    /**
     * ربط أحداث زر المرفقات
     */
    attachEventListeners: function() {
        // زر "إدارة ذكية" بجانب كل مرفق
        document.addEventListener('click', (e) => {
            if (e.target.closest('.smart-manage-btn')) {
                const btn = e.target.closest('.smart-manage-btn');
                this.openSmartMerge(
                    btn.dataset.attId,
                    btn.dataset.fileUrl,
                    btn.dataset.fileName
                );
            }
        });
    },

    /**
     * ربط أحداث Modal
     */
    attachModalEventListeners: function() {
        // أزرار الإجراءات الثلاثة
        document.querySelectorAll('.merge-action-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                this.handleActionSelect(action);
            });
        });

        // زر تنفيذ العملية
        document.getElementById('executeActionBtn').addEventListener('click', () => {
            this.executeAction();
        });

        // تحديث اسم الملف عند اختياره
        const fileInput = document.getElementById('mergeFileInput');
        if (fileInput) {
            fileInput.addEventListener('change', (e) => {
                const label = fileInput.nextElementSibling;
                if (e.target.files.length > 0) {
                    label.textContent = e.target.files[0].name;
                } else {
                    label.textContent = 'اختر ملف...';
                }
            });
        }
    },

    /**
     * فتح modal الدمج الذكي
     */
    openSmartMerge: function(attId, fileUrl, fileName) {
        this.currentAttachmentId = attId;
        this.currentFileUrl = fileUrl;
        this.currentFileName = fileName;

        // تحديث العنوان
        document.getElementById('currentFileName').textContent = fileName;

        // إعادة تعيين الحالة
        this.resetModal();

        // تحميل سجل الإصدارات
        this.loadVersionsHistory();

        // فتح Modal
        $(this.mergeModalEl).modal('show');
    },

    /**
     * التعامل مع اختيار الإجراء
     */
    handleActionSelect: function(action) {
        // إخفاء جميع الأقسام
        document.getElementById('fileInputSection').style.display = 'none';
        document.getElementById('deleteConfirmSection').style.display = 'none';
        document.getElementById('mergeTypeSection').style.display = 'none';

        // إظهار الأقسام المناسبة
        const executeBtn = document.getElementById('executeActionBtn');
        
        switch(action) {
            case 'delete':
                document.getElementById('deleteConfirmSection').style.display = 'block';
                executeBtn.textContent = 'تأكيد الحذف';
                executeBtn.classList.remove('btn-primary', 'btn-success', 'btn-warning');
                executeBtn.classList.add('btn-danger');
                executeBtn.dataset.action = 'delete';
                executeBtn.style.display = 'block';
                break;

            case 'merge':
                document.getElementById('fileInputSection').style.display = 'block';
                document.getElementById('mergeTypeSection').style.display = 'block';
                executeBtn.textContent = 'تنفيذ الدمج';
                executeBtn.classList.remove('btn-primary', 'btn-danger', 'btn-success');
                executeBtn.classList.add('btn-warning');
                executeBtn.dataset.action = 'merge';
                executeBtn.style.display = 'block';
                break;

            case 'upload':
                document.getElementById('fileInputSection').style.display = 'block';
                executeBtn.textContent = 'إضافة الملف';
                executeBtn.classList.remove('btn-primary', 'btn-danger', 'btn-warning');
                executeBtn.classList.add('btn-success');
                executeBtn.dataset.action = 'upload';
                executeBtn.style.display = 'block';
                break;
        }
    },

    /**
     * تنفيذ العملية المختارة
     */
    executeAction: async function() {
        const action = document.getElementById('executeActionBtn').dataset.action;

        if (this.isProcessing) {
            this.notify('هناك عملية جارية بالفعل، يرجى الانتظار حتى تكتمل.', 'warning', 'المعالجة مستمرة');
            return;
        }

        this.isProcessing = true;
        this.showProgress();

        try {
            switch(action) {
                case 'delete':
                    await this.deleteFile();
                    break;
                case 'merge':
                    await this.mergeFile();
                    break;
                case 'upload':
                    await this.uploadFile();
                    break;
            }
        } catch (error) {
            this.showMessage('خطأ: ' + error.message, 'danger');
        } finally {
            this.isProcessing = false;
            this.hideProgress();
        }
    },

    /**
     * حذف الملف
     */
    deleteFile: async function() {
        const reason = document.getElementById('deleteReason').value;

        const response = await fetch(`/books/api/attachments/${this.currentAttachmentId}/delete_file/`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({ reason })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'خطأ في حذف الملف');
        }

        const data = await response.json();
        this.showMessage('تم حذف الملف بنجاح', 'success');
        
        // تحديث الواجهة
        setTimeout(() => {
            location.reload();
        }, 2000);
    },

    /**
     * دمج الملفات
     */
    mergeFile: async function() {
        const fileInput = document.getElementById('mergeFileInput');
        if (!fileInput.files.length) {
            throw new Error('يجب اختيار ملف');
        }

        const mergeType = document.querySelector('input[name="mergeType"]:checked').value;
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('merge_type', mergeType);

        const response = await fetch(`/books/api/attachments/${this.currentAttachmentId}/merge/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCsrfToken()
            },
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'خطأ في دمج الملفات');
        }

        const data = await response.json();
        this.showMessage('تم دمج الملفات بنجاح', 'success');
        
        // تحديث الواجهة
        setTimeout(() => {
            location.reload();
        }, 2000);
    },

    /**
     * إضافة ملف جديد
     */
    uploadFile: async function() {
        const fileInput = document.getElementById('mergeFileInput');
        if (!fileInput.files.length) {
            throw new Error('يجب اختيار ملف');
        }

        // هذه العملية ستكون مشابهة للدمج لكن بدون دمج فعلي
        // ستحفظ الملف كنسخة جديدة منفصلة
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('merge_type', 'none');

        const response = await fetch(`/books/api/attachments/${this.currentAttachmentId}/merge/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCsrfToken()
            },
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'خطأ في إضافة الملف');
        }

        const data = await response.json();
        this.showMessage('تم إضافة الملف بنجاح', 'success');
        
        // تحديث الواجهة
        setTimeout(() => {
            location.reload();
        }, 2000);
    },

    /**
     * تحميل سجل الإصدارات
     */
    loadVersionsHistory: async function() {
        try {
            const response = await fetch(`/books/api/attachments/${this.currentAttachmentId}/versions/`);
            if (!response.ok) throw new Error('خطأ في تحميل الإصدارات');

            const data = await response.json();
            const list = document.getElementById('versionsList');
            
            if (data.versions.length === 0) {
                list.innerHTML = '<p class="text-muted">لا توجد نسخ سابقة</p>';
                return;
            }

            list.innerHTML = data.versions.map(v => `
                <div class="card mb-2" style="font-size: 0.9em;">
                    <div class="card-body py-2 px-3">
                        <small class="text-muted">النسخة ${v.version_number}</small>
                        <div>${new Date(v.created_at).toLocaleString('ar-EG')}</div>
                        ${v.is_merged ? `<span class="badge badge-info">مدمجة</span>` : ''}
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('خطأ في تحميل سجل الإصدارات:', error);
        }
    },

    /**
     * عرض رسالة
     */
    showMessage: function(text, type = 'info') {
        const messageDiv = document.getElementById('mergeMessage');
        messageDiv.className = `alert alert-${type} alert-dismissible fade show`;
        messageDiv.style.display = 'block';
        document.getElementById('mergeMessageText').textContent = text;
    },

    /**
     * عرض شريط التقدم
     */
    showProgress: function() {
        document.getElementById('mergeProgress').style.display = 'block';
        const progressBar = document.getElementById('progressBar');
        let progress = 0;
        const interval = setInterval(() => {
            progress = Math.min(progress + Math.random() * 30, 90);
            progressBar.style.width = progress + '%';
        }, 200);
        document.getElementById('mergeProgress').dataset.interval = interval;
    },

    /**
     * إخفاء شريط التقدم
     */
    hideProgress: function() {
        const interval = document.getElementById('mergeProgress').dataset.interval;
        clearInterval(interval);
        const progressBar = document.getElementById('progressBar');
        progressBar.style.width = '100%';
        setTimeout(() => {
            document.getElementById('mergeProgress').style.display = 'none';
        }, 500);
    },

    /**
     * إعادة تعيين Modal
     */
    resetModal: function() {
        document.getElementById('fileInputSection').style.display = 'none';
        document.getElementById('deleteConfirmSection').style.display = 'none';
        document.getElementById('mergeTypeSection').style.display = 'none';
        document.getElementById('mergeMessage').style.display = 'none';
        document.getElementById('mergeProgress').style.display = 'none';
        document.getElementById('executeActionBtn').style.display = 'none';
        document.getElementById('mergeFileInput').value = '';
        document.getElementById('deleteReason').value = '';
        document.getElementById('mergeTypeSmart').checked = true;
    },

    /**
     * الحصول على CSRF Token
     */
    getCsrfToken: function() {
        return document.querySelector('[name=csrfmiddlewaretoken]').value;
    }
};

// تهيئة الواجهة عند تحميل الصفحة
document.addEventListener('DOMContentLoaded', () => {
    SmartMergeUI.init();
});
