document.addEventListener('DOMContentLoaded', function() {
    // Modern form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Modern button loading states
    const buttons = document.querySelectorAll('button[type="submit"]');
    buttons.forEach(button => {
        button.addEventListener('click', function() {
            if (this.form && this.form.checkValidity()) {
                this.classList.add('btn-loading');
            }
        });
    });

    // Modern table sorting and alignment
    const tables = document.querySelectorAll('table');
    tables.forEach(table => {
        // Add responsive wrapper if needed
        if (!table.classList.contains('table-responsive')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'table-responsive';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }

        // Add sorting functionality
        const headers = table.querySelectorAll('th');
        headers.forEach(header => {
            if (header.dataset.sortable !== 'false') {
                header.style.cursor = 'pointer';
                header.addEventListener('click', () => {
                    const index = Array.from(header.parentElement.children).indexOf(header);
                    const rows = Array.from(table.querySelectorAll('tbody tr'));
                    const direction = header.dataset.direction === 'asc' ? -1 : 1;
                    
                    rows.sort((a, b) => {
                        const aValue = a.children[index].textContent.trim();
                        const bValue = b.children[index].textContent.trim();
                        
                        if (!isNaN(aValue) && !isNaN(bValue)) {
                            return direction * (Number(aValue) - Number(bValue));
                        }
                        return direction * aValue.localeCompare(bValue);
                    });
                    
                    header.dataset.direction = direction === 1 ? 'asc' : 'desc';
                    table.querySelector('tbody').append(...rows);
                });
            }
        });
    });

    // Modern alerts auto-dismiss
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Modern tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl, {
            trigger: 'hover'
        });
    });

    // Modern dropdown menus
    const dropdowns = document.querySelectorAll('.dropdown-toggle');
    dropdowns.forEach(dropdown => {
        dropdown.addEventListener('click', function(e) {
            e.preventDefault();
            const menu = this.nextElementSibling;
            menu.classList.toggle('show');
        });
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.matches('.dropdown-toggle')) {
            document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
                menu.classList.remove('show');
            });
        }
    });

    // Modern scroll to top button
    const scrollTopBtn = document.createElement('button');
    scrollTopBtn.innerHTML = '<i class="bi bi-arrow-up"></i>';
    scrollTopBtn.className = 'scroll-top-btn';
    document.body.appendChild(scrollTopBtn);

    let scrollTimeout;
    window.addEventListener('scroll', () => {
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
            if (window.pageYOffset > 100) {
                scrollTopBtn.classList.add('visible');
            } else {
                scrollTopBtn.classList.remove('visible');
            }
        }, 100);
    });

    scrollTopBtn.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });

    // Modern responsive tables
    const responsiveTables = document.querySelectorAll('.table-responsive');
    responsiveTables.forEach(table => {
        const wrapper = document.createElement('div');
        wrapper.className = 'table-responsive-wrapper';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);

        const scrollBtn = document.createElement('button');
        scrollBtn.className = 'btn btn-sm btn-light position-absolute end-0 top-50 translate-middle-y d-md-none';
        scrollBtn.innerHTML = '<i class="bi bi-arrow-right"></i>';
        wrapper.appendChild(scrollBtn);

        let isScrolling = false;
        scrollBtn.addEventListener('click', () => {
            if (!isScrolling) {
                isScrolling = true;
                const scrollAmount = table.offsetWidth * 0.8;
                table.scrollBy({
                    left: scrollAmount,
                    behavior: 'smooth'
                });
                setTimeout(() => {
                    isScrolling = false;
                }, 500);
            }
        });
    });

    // Modern form input effects
    const inputs = document.querySelectorAll('.form-control, .form-select');
    inputs.forEach(input => {
        input.addEventListener('focus', function() {
            this.parentElement.classList.add('focused');
        });
        input.addEventListener('blur', function() {
            if (!this.value) {
                this.parentElement.classList.remove('focused');
            }
        });
    });

    // Fix FAQ link in admin edit item
    const faqLinks = document.querySelectorAll('a[href="/faq"]');
    faqLinks.forEach(link => {
        if (link.closest('.admin-edit-item')) {
            link.href = '../faq';
        }
    });
});
  