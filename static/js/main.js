/* ========================================
   السكريبتات المشتركة للموقع
   ======================================== */

// ========== بيانات الفئات ==========
window.categoriesData = window.categoriesData || [];

// ========== تحميل الفئات من API ==========
async function loadCategoriesFromAPI() {
    try {
        const response = await fetch('/api/categories');
        const data = await response.json();
        
        if (data.status === 'success' && data.categories) {
            window.categoriesData = data.categories;
            return data.categories;
        }
        return [];
    } catch (e) {
        console.error('Error loading categories:', e);
        return [];
    }
}

// ========== التوست ==========
function showToast(message, type = 'success', actionText = null, actionCallback = null) {
    let toast = document.getElementById('globalToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'globalToast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    
    // تحديد الأيقونة حسب النوع
    let icon = '✅';
    if (type === 'error') icon = '❌';
    else if (type === 'warning') icon = '⚠️';
    else if (type === 'info') icon = 'ℹ️';
    
    // بناء محتوى التوست
    let html = `<span class="toast-icon">${icon}</span><span class="toast-message">${message}</span>`;
    
    // إضافة زر الإجراء إذا موجود
    if (actionText && actionCallback) {
        html += `<button class="toast-action" id="toastAction">${actionText}</button>`;
    }
    
    toast.innerHTML = html;
    toast.className = 'toast ' + type;
    
    // ربط زر الإجراء
    if (actionText && actionCallback) {
        document.getElementById('toastAction').onclick = function() {
            actionCallback();
            toast.classList.remove('show');
        };
    }
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => toast.classList.remove('show'), 3500);
}

// ========== إغلاق بـ Escape ==========
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        // إغلاق sidebar
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        if (sidebar && sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
            if (overlay) overlay.classList.remove('open');
        }
        
        // إغلاق أي modal مفتوح
        document.querySelectorAll('.modal-overlay.active, .modal-overlay.show, .modal.show').forEach(modal => {
            modal.classList.remove('active');
            modal.classList.remove('show');
        });
        document.body.style.overflow = 'auto';
    }
});

// ========== تحميل الفئات عند فتح الصفحة ==========
document.addEventListener('DOMContentLoaded', function() {
    // تحميل الفئات إذا لم تكن موجودة
    if (!window.categoriesData || window.categoriesData.length === 0) {
        loadCategoriesFromAPI();
    }
});
