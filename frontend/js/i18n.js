// Система локалізації для Client Onboarding Service
// Підтримує українську (UK) та англійську (EN) мови

// Словник перекладів
const translations = {
  uk: {
    // Header
    'header.title': 'Client Onboarding',
    'header.subtitle': 'Швидке підключення клієнтів',
    'header.description': 'ACM сертифікати, PR до фронтенду, Ingress у кластер — все в одному інтерфейсі.',
    'header.clients-link': 'Клієнти →',
    
    // Stats widget
    'stats.certificates': 'Сертифікати',
    'stats.loading': 'Завантаження...',
    'stats.free': 'вільно',
    'stats.exceeded': 'перевищено на',
    'stats.alb': 'ALB',
    'stats.load-error': 'Помилка завантаження',
    
    // Create client card
    'create.title': 'Створити клієнта',
    'create.domain': 'Domain',
    'create.domain.placeholder': 'example.com',
    'create.subdomain': 'Subdomain',
    'create.subdomain.placeholder': 'patient',
    'create.affiliate': 'Affiliate',
    'create.affiliate.placeholder': 'UUID',
    'create.alb-group': 'ALB group.name (опційно)',
    'create.alb-group.placeholder': 'telemd-public3',
    'create.create-pr': 'Створити PR у фронтенд-репо',
    'create.auto-merge': 'Авто-мердж PR',
    'create.submit': 'Створити',
    
    // Apply manifest card
    'apply.title': 'Застосувати маніфест',
    'apply.ingress-path': 'Ingress path',
    'apply.ingress-path.placeholder': '/abs/path/to/prod/patient.example.com.yaml',
    'apply.submit': 'Apply',
    
    // Reissue certificate card
    'reissue.title': 'Повторити запит сертифіката',
    'reissue.domain': 'Domain',
    'reissue.domain.placeholder': 'example.com',
    'reissue.auto-actions-title': 'Автоматичні дії',
    'reissue.action-update-database': 'Оновлення ARN в базі даних',
    'reissue.action-update-ingress': 'Оновлення файлів інгресу',
    'reissue.action-delete-cert': 'Видалення старого сертифіката',
    'reissue.submit': 'Reissue Full',
    
    // Results and messages
    'result.id': 'ID',
    'result.certificate-arn': 'Certificate ARN',
    'result.dns-name': 'DNS Name',
    'result.dns-value': 'DNS Value',
    'result.ingress': 'Ingress',
    'result.group': 'Group',
    'result.status': 'Status',
    'result.old-certificate-arn': 'Old Certificate ARN',
    'result.new-certificate-arn': 'New Certificate ARN',
    'result.updated-clients': 'Оновлено клієнтів',
    'result.updated-files': 'Оновлено файлів',
    'result.dns-validation': 'DNS Валідація',
    'result.next-steps': 'Наступні кроки',
    'result.warning': 'Попередження',
    'result.error': 'Помилка',
    'result.success': 'Успішно оновлено!',
    'result.none': 'Немає',
    
    // Clients page
    'clients.title': 'Керування клієнтами',
    'clients.description': 'Перегляд статусу клієнтів, сертифікатів і можливість розгортання',
    'clients.back-link': '← Головна',
    'clients.table.name': 'Ім\'\u044f',
    'clients.table.certificate': 'Статус сертифіката',
    'clients.table.alb-status': 'ALB',
    'clients.table.cert-dns-status': 'Cert DNS',
    'clients.table.client-dns-status': 'Client DNS',
    'clients.table.web-status': 'Веб',
    'clients.table.actions': 'Дії',
    'clients.button.check-certificate': 'Перевірити сертифікат',
    'clients.button.deploy': 'Розгорнути',
    'clients.button.refresh': 'Оновити',
    'clients.button.refresh-k8s': 'Оновити стан K8s',
    'clients.button.import': 'Імпортувати',
    'clients.button.check-all-dns': 'Перевірити всі DNS',
    'clients.button.alb-stats': 'ALB групи',
    'clients.filter.placeholder': 'Фільтр за доменом (наприклад, example.com)',
    'clients.button.applied': '✓ Застосовано',
    'clients.button.deploy-ingress': 'Деплой інгрес',
    'clients.button.unavailable': 'Недоступно',
    'clients.empty': 'Порожньо',
    'clients.loading': 'Завантаження...',
    
    // Language switcher
    'lang.current': 'Українська',
    'lang.switch-to': 'English'
  },
  
  en: {
    // Header
    'header.title': 'Client Onboarding',
    'header.subtitle': 'Fast client onboarding',
    'header.description': 'ACM certificates, frontend PRs, Ingress to cluster — all in one interface.',
    'header.clients-link': 'Clients →',
    
    // Stats widget
    'stats.certificates': 'Certificates',
    'stats.loading': 'Loading...',
    'stats.free': 'free',
    'stats.exceeded': 'exceeded by',
    'stats.alb': 'ALB',
    'stats.load-error': 'Loading error',
    
    // Create client card
    'create.title': 'Create Client',
    'create.domain': 'Domain',
    'create.domain.placeholder': 'example.com',
    'create.subdomain': 'Subdomain',
    'create.subdomain.placeholder': 'patient',
    'create.affiliate': 'Affiliate',
    'create.affiliate.placeholder': 'UUID',
    'create.alb-group': 'ALB group.name (optional)',
    'create.alb-group.placeholder': 'telemd-public3',
    'create.create-pr': 'Create PR in frontend repo',
    'create.auto-merge': 'Auto-merge PR',
    'create.submit': 'Create',
    
    // Apply manifest card
    'apply.title': 'Apply Manifest',
    'apply.ingress-path': 'Ingress path',
    'apply.ingress-path.placeholder': '/abs/path/to/prod/patient.example.com.yaml',
    'apply.submit': 'Apply',
    
    // Reissue certificate card
    'reissue.title': 'Reissue Certificate',
    'reissue.domain': 'Domain',
    'reissue.domain.placeholder': 'example.com',
    'reissue.auto-actions-title': 'Automatic actions',
    'reissue.action-update-database': 'Update ARN in database',
    'reissue.action-update-ingress': 'Update ingress files',
    'reissue.action-delete-cert': 'Delete old certificate',
    'reissue.submit': 'Reissue Full',
    
    // Results and messages
    'result.id': 'ID',
    'result.certificate-arn': 'Certificate ARN',
    'result.dns-name': 'DNS Name',
    'result.dns-value': 'DNS Value',
    'result.ingress': 'Ingress',
    'result.group': 'Group',
    'result.status': 'Status',
    'result.old-certificate-arn': 'Old Certificate ARN',
    'result.new-certificate-arn': 'New Certificate ARN',
    'result.updated-clients': 'Clients updated',
    'result.updated-files': 'Files updated',
    'result.dns-validation': 'DNS Validation',
    'result.next-steps': 'Next steps',
    'result.warning': 'Warning',
    'result.error': 'Error',
    'result.success': 'Successfully updated!',
    'result.none': 'None',
    
    // Clients page
    'clients.title': 'Client Management',
    'clients.description': 'View client status, certificates and deployment options',
    'clients.back-link': '← Home',
    'clients.table.name': 'Name',
    'clients.table.certificate': 'Certificate Status',
    'clients.table.alb-status': 'ALB',
    'clients.table.cert-dns-status': 'Cert DNS',
    'clients.table.client-dns-status': 'Client DNS',
    'clients.table.web-status': 'Web',
    'clients.table.actions': 'Actions',
    'clients.button.check-certificate': 'Check Certificate',
    'clients.button.deploy': 'Deploy',
    'clients.button.refresh': 'Refresh',
    'clients.button.refresh-k8s': 'Refresh K8s State',
    'clients.button.import': 'Import',
    'clients.button.check-all-dns': 'Check All DNS',
    'clients.button.alb-stats': 'ALB Groups',
    'clients.filter.placeholder': 'Filter by domain (e.g., example.com)',
    'clients.button.applied': '✓ Applied',
    'clients.button.deploy-ingress': 'Deploy Ingress',
    'clients.button.unavailable': 'Unavailable',
    'clients.empty': 'Empty',
    'clients.loading': 'Loading...',
    
    // Language switcher
    'lang.current': 'English',
    'lang.switch-to': 'Українська'
  }
};

// Поточна мова (за замовчуванням українська)
let currentLanguage = localStorage.getItem('language') || 'uk';

// Функція отримання перекладу
function t(key) {
  return translations[currentLanguage][key] || translations['uk'][key] || key;
}

// Функція встановлення мови
function setLanguage(lang) {
  console.log('setLanguage called with:', lang);
  if (lang !== 'uk' && lang !== 'en') {
    console.warn('Unsupported language:', lang);
    return;
  }
  
  currentLanguage = lang;
  localStorage.setItem('language', lang);
  console.log('language set to:', currentLanguage);
  updatePageTexts();
  updateLanguageSwitcher();
}

// Функція оновлення всіх текстів на сторінці
function updatePageTexts() {
  // Оновлюємо всі елементи з атрибутом data-i18n
  document.querySelectorAll('[data-i18n]').forEach(element => {
    const key = element.getAttribute('data-i18n');
    const translation = t(key);
    
    // Перевіряємо тип елемента
    if (element.tagName === 'INPUT') {
      // Для всіх типів інпутів, які можуть мати placeholder
      if (element.type === 'text' || element.type === 'email' || element.type === 'search' || 
          element.type === 'password' || element.type === 'url' || element.type === 'tel' || 
          !element.type || element.type === '') {
        element.placeholder = translation;
      } else if (element.type === 'submit' || element.type === 'button') {
        // Для кнопок встановлюємо значення
        element.value = translation;
      }
      // Не змінюємо значення для чекбоксів, радіо та інших типів
    } else {
      element.textContent = translation;
    }
  });
  
  // Оновлюємо атрибути title
  document.querySelectorAll('[data-i18n-title]').forEach(element => {
    const key = element.getAttribute('data-i18n-title');
    element.title = t(key);
  });
  
  // Оновлюємо HTML контент (для складних елементів)
  document.querySelectorAll('[data-i18n-html]').forEach(element => {
    const key = element.getAttribute('data-i18n-html');
    element.innerHTML = t(key);
  });
}

// Функція оновлення перемикача мов
function updateLanguageSwitcher() {
  const currentLangElement = document.getElementById('current-lang');
  const switchLangElement = document.getElementById('switch-lang');
  const flagIcon = document.getElementById('flag-icon');
  
  if (currentLangElement) {
    currentLangElement.textContent = t('lang.current');
  }
  
  if (switchLangElement) {
    switchLangElement.textContent = t('lang.switch-to');
  }
  
  // Оновлення прапора
  if (flagIcon) {
    flagIcon.className = `flag flag-${currentLanguage}`;
  }
}

// Функція перемикання мови
function toggleLanguage() {
  console.log('toggleLanguage called, current:', currentLanguage);
  const newLang = currentLanguage === 'uk' ? 'en' : 'uk';
  console.log('switching to:', newLang);
  setLanguage(newLang);
  
  // Викинути подію для сповіщення інших частин сторінки
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('languageChanged', {
      detail: { language: newLang }
    }));
  }
}

// Ініціалізація при завантаженні сторінки
document.addEventListener('DOMContentLoaded', function() {
  updatePageTexts();
  updateLanguageSwitcher();
});

// Експорт функцій для глобального використання
window.i18n = {
  t,
  setLanguage,
  toggleLanguage,
  updatePageTexts,
  getCurrentLanguage: () => currentLanguage
};

// Експорт toggleLanguage глобально для HTML onclick
window.toggleLanguage = toggleLanguage;