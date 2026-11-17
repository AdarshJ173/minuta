/* Minuta landing: progressive enhancement only. No framework, no build. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Copy buttons */
  document.querySelectorAll("[data-copy],[data-copy-target]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy") ||
        (document.getElementById(btn.getAttribute("data-copy-target")) || {}).innerText || "";
      function done() {
        var old = btn.textContent; btn.textContent = "Copied ✓";
        setTimeout(function () { btn.textContent = old; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        ta.remove(); done();
      }
    });
  });

  /* Smooth scroll (Lenis) + reveals (GSAP): both optional */
  try {
    if (!reduced && window.Lenis) {
      var lenis = new Lenis({ lerp: 0.11 });
      if (window.gsap) {
        lenis.on("scroll", function () {
          if (window.ScrollTrigger) window.ScrollTrigger.update();
        });
        gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
        gsap.ticker.lagSmoothing(0);
      } else {
        (function raf(t) { lenis.raf(t); requestAnimationFrame(raf); })(0);
      }
      document.querySelectorAll('a[href^="#"]').forEach(function (a) {
        a.addEventListener("click", function (e) {
          var el = document.querySelector(a.getAttribute("href"));
          if (el) { e.preventDefault(); lenis.scrollTo(el, { offset: -70 }); }
        });
      });
    }
  } catch (e) {}

  try {
    if (window.gsap && window.ScrollTrigger && !reduced) {
      gsap.registerPlugin(ScrollTrigger);
      gsap.utils.toArray(".reveal").forEach(function (el, i) {
        gsap.to(el, {
          opacity: 1, y: 0, duration: 0.9, ease: "power3.out",
          delay: (i % 3) * 0.06,
          scrollTrigger: { trigger: el, start: "top 88%", once: true }
        });
      });
    } else {
      document.body.classList.add("no-motion");
    }
  } catch (e) {
    document.body.classList.add("no-motion");
  }
  if (reduced) document.body.classList.add("no-motion");

  /* Hairline figure (real thing, auto-playing). Falls back to the
     hand-drawn cue canvas if the CDN is unreachable. */
  (function () {
    var host = document.getElementById("hl");
    if (!host) { initCuesFallback(); return; }
    function fail() {
      var cv = document.getElementById("cues");
      if (cv) { cv.hidden = false; host.style.display = "none"; }
      initCuesFallback();
    }
    if (reduced) {
      try {
        import("https://cdn.jsdelivr.net/npm/@lucasmarkes/hairline@latest/+esm").then(function (m) {
          m.phosphor(host, { play: false, intensity: 0.5,
            label: "Dot matrix wordmark field at rest" });
        }).catch(fail);
      } catch (e) { fail(); }
      return;
    }
    var started = false;
    function boot() {
      if (started) return; started = true;
      import("https://cdn.jsdelivr.net/npm/@lucasmarkes/hairline@latest/+esm").then(function (m) {
        m.phosphor(host, { play: true, intensity: 0.7,
          label: "Dot matrix that plays a loop. Your pointer paints phosphor trails." });
      }).catch(fail);
    }
    if ("IntersectionObserver" in window) {
      var once = new IntersectionObserver(function (es) {
        if (es[0].isIntersecting) { boot(); once.disconnect(); }
      });
      once.observe(host);
    } else { boot(); }
  })();

  /* Hand-drawn cue-canvas fallback: thin transcript-cue bars that answer
     the pointer. One loop, pauses offscreen, rests when idle. */
  function initCuesFallback() {
    var cv = document.getElementById("cues");
    if (!cv || !cv.getContext) return;
    var ctx = cv.getContext("2d");
    var W = 0, H = 180, bars = [], px = -9999, py = -9999;
    var scan = 0, active = true, running = false, seen = false;

    function build() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = cv.clientWidth; cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      bars = [];
      var rows = 7, i, x, r;
      for (r = 0; r < rows; r++) {
        x = 14 + ((r * 53) % 60);
        while (x < W - 30) {
          var w = 26 + ((r * 37 + x * 13) % 90);
          bars.push({ x: x, w: Math.min(w, W - x - 14), y: 22 + r * 20, r: r });
          x += w + 14 + ((r * 29 + x) % 46);
        }
      }
      draw(0);
    }

    function draw(t) {
      ctx.clearRect(0, 0, W, H);
      var i, b, dx, p, lift;
      for (i = 0; i < bars.length; i++) {
        b = bars[i];
        dx = Math.abs((b.x + b.w / 2) - px);
        p = Math.max(0, 1 - dx / 150);
        if (!seen) p = Math.max(p, Math.max(0, 1 - Math.abs((b.x + b.w / 2) - scan) / 220) * 0.8);
        lift = p * 5;
        ctx.strokeStyle = p > 0.55 ? "#141412" : (p > 0.2 ? "#8A867E" : "#DCD8CE");
        ctx.lineWidth = p > 0.55 ? 1.6 : 1;
        ctx.beginPath();
        ctx.moveTo(b.x, b.y - lift);
        ctx.lineTo(b.x + b.w, b.y - lift);
        ctx.stroke();
        if (p > 0.75) {
          ctx.fillStyle = "#FF4D00";
          ctx.beginPath();
          ctx.arc(b.x + b.w / 2, b.y - lift - 7, 2, 0, 6.2832);
          ctx.fill();
        }
      }
    }

    function loop(t) {
      if (!active) { running = false; return; }
      running = true;
      if (!reduced) scan = (t / 14) % (W + 300) - 150;
      draw(t);
      requestAnimationFrame(loop);
    }
    function kick() { if (active && !running) requestAnimationFrame(loop); }

    cv.addEventListener("pointermove", function (e) {
      var r = cv.getBoundingClientRect();
      px = e.clientX - r.left; py = e.clientY - r.top; seen = true; kick();
    });
    cv.addEventListener("pointerleave", function () { px = -9999; kick(); });

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        active = es[0].isIntersecting; kick();
      }).observe(cv);
    }
    if ("ResizeObserver" in window) new ResizeObserver(build).observe(cv);
    window.addEventListener("resize", build);
    build(); kick();
  }
})();
