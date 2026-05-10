// CloudSentro — small UX layer
// No frameworks, no CDN dependencies. Single-file, lazy-loaded.

(function () {
  "use strict";

  // ── reveal-on-scroll ───────────────────────────────────────────────
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -80px 0px", threshold: 0.05 }
    );
    document.querySelectorAll(".reveal").forEach(function (el) {
      observer.observe(el);
    });
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("visible");
    });
  }

  // ── counter animation ──────────────────────────────────────────────
  function animateCount(el) {
    const target = parseFloat(el.dataset.count || el.textContent);
    if (isNaN(target)) return;
    const suffix = el.dataset.suffix || "";
    const decimals = parseInt(el.dataset.decimals || "0", 10);
    const duration = 1200;
    const start = performance.now();
    function step(now) {
      const t = Math.min(1, (now - start) / duration);
      const ease = 1 - Math.pow(1 - t, 3);
      const v = target * ease;
      el.textContent = v.toFixed(decimals) + suffix;
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = target.toFixed(decimals) + suffix;
    }
    requestAnimationFrame(step);
  }

  const numbers = document.querySelectorAll(".stat .num[data-count]");
  if ("IntersectionObserver" in window && numbers.length) {
    const numObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            animateCount(entry.target);
            numObs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.4 }
    );
    numbers.forEach(function (n) { numObs.observe(n); });
  }

  // ── mobile nav toggle ──────────────────────────────────────────────
  const toggle = document.querySelector(".nav-toggle");
  const links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      links.classList.toggle("open");
      toggle.setAttribute(
        "aria-expanded",
        links.classList.contains("open") ? "true" : "false"
      );
    });
  }

  // ── tabs ──────────────────────────────────────────────────────────
  document.querySelectorAll("[data-tabs]").forEach(function (root) {
    const buttons = root.querySelectorAll(".tab");
    const panels = root.querySelectorAll(".tab-panel");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = btn.dataset.tab;
        buttons.forEach(function (b) { b.classList.toggle("active", b === btn); });
        panels.forEach(function (p) {
          p.classList.toggle("active", p.dataset.panel === id);
        });
      });
    });
  });

  // ── terminal typing animation ──────────────────────────────────────
  const terminal = document.querySelector("[data-terminal]");
  if (terminal) {
    const script = window.__terminalScript || [];
    let lineIdx = 0;
    function next() {
      if (lineIdx >= script.length) return;
      const line = script[lineIdx];
      const div = document.createElement("div");
      div.innerHTML = line.html;
      terminal.appendChild(div);
      terminal.scrollTop = terminal.scrollHeight;
      lineIdx += 1;
      setTimeout(next, line.delay || 600);
    }
    function start() {
      if ("IntersectionObserver" in window) {
        const obs = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              next();
              obs.disconnect();
            }
          });
        }, { threshold: 0.3 });
        obs.observe(terminal);
      } else {
        next();
      }
    }
    start();
  }

  // ── smooth section nav highlight ───────────────────────────────────
  const navLinks = document.querySelectorAll(".nav-links a[href^='#']");
  if (navLinks.length) {
    const sections = Array.from(navLinks)
      .map(function (a) { return document.querySelector(a.getAttribute("href")); })
      .filter(Boolean);
    if ("IntersectionObserver" in window && sections.length) {
      const navObs = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            navLinks.forEach(function (a) {
              a.classList.toggle("active", a.getAttribute("href") === "#" + entry.target.id);
            });
          }
        });
      }, { rootMargin: "-30% 0px -60% 0px", threshold: 0 });
      sections.forEach(function (s) { navObs.observe(s); });
    }
  }
})();
