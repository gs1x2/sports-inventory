document.addEventListener('DOMContentLoaded', function() {
    // Пример лёгкой анимации при клике на ссылки/кнопки
    const clickableElements = document.querySelectorAll('.nav-link, .btn');
    
    clickableElements.forEach(el => {
      el.addEventListener('click', () => {
        document.body.style.transition = 'opacity 0.3s';
        document.body.style.opacity = '0.5';
        setTimeout(() => {
          document.body.style.opacity = '1';
        }, 500);
      });
    });
  });
  