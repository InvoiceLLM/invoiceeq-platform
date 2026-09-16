// InvoiceEQ Product Catalog — Interactive behaviors

// ─── Nav scroll shadow ───────────────────────────────────────────────────────
const nav = document.getElementById('nav') || document.querySelector('.nav');
if (nav) {
  window.addEventListener('scroll', () => {
    nav.style.borderBottomColor = window.scrollY > 10
      ? 'rgba(76,141,255,0.2)'
      : 'var(--border)';
  }, { passive: true });
}

// ─── FAQ accordion ───────────────────────────────────────────────────────────
function toggleFaq(btn) {
  const answer = btn.nextElementSibling;
  const isOpen = btn.classList.contains('open');

  // Close all open FAQs
  document.querySelectorAll('.faq-q.open').forEach(q => {
    q.classList.remove('open');
    q.nextElementSibling.classList.remove('open');
  });

  // Open clicked one if it was closed
  if (!isOpen) {
    btn.classList.add('open');
    answer.classList.add('open');
  }
}

// ─── Scroll-triggered fade-in animations ─────────────────────────────────────
const animTargets = document.querySelectorAll(
  '.metric-card, .module-card, .role-card, .fail-card, ' +
  '.limit-item, .scenario-card, .pipeline-step, ' +
  '.security-card, .deployment-card'
);

if ('IntersectionObserver' in window && animTargets.length) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-in');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

  animTargets.forEach((el, i) => {
    el.style.opacity = '0';
    el.style.animationDelay = `${(i % 4) * 0.08}s`;
    io.observe(el);
  });
}

// ─── Active nav link based on current page ────────────────────────────────────
const currentPage = window.location.pathname.split('/').pop() || 'index.html';
document.querySelectorAll('.nav-link').forEach(link => {
  const href = link.getAttribute('href');
  if (href === currentPage || (currentPage === '' && href === 'index.html')) {
    link.classList.add('active');
  } else {
    link.classList.remove('active');
  }
});

// ─── Smooth scroll for anchor links ──────────────────────────────────────────
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function(e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ─── Maturity ladder highlight on hover ──────────────────────────────────────
document.querySelectorAll('.maturity-table tbody tr').forEach(row => {
  row.addEventListener('mouseenter', () => {
    if (!row.classList.contains('level-active')) {
      row.style.opacity = '1';
    }
  });
  row.addEventListener('mouseleave', () => {
    if (!row.classList.contains('level-active')) {
      row.style.opacity = '';
    }
  });
});
