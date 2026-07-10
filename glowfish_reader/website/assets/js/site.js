(function () {
  "use strict";

  function headerOffset() {
    var header = document.querySelector(".masthead");
    return (header ? header.getBoundingClientRect().height : 0) + 12;
  }

  function scrollToHash(hash, behavior) {
    if (!hash || hash === "#") return false;
    var target = document.querySelector(hash);
    if (!target) return false;

    var top = target.getBoundingClientRect().top + window.pageYOffset - headerOffset();
    window.scrollTo({
      top: Math.max(0, top),
      behavior: behavior || "smooth"
    });
    return true;
  }

  function settleHashPosition() {
    if (!window.location.hash) return;
    [0, 80, 240, 520].forEach(function (delay) {
      window.setTimeout(function () {
        scrollToHash(window.location.hash, "auto");
      }, delay);
    });
  }

  function jumpShowcase(link) {
    if (!link.matches("[data-showcase-jump]")) return;

    var index = Number(link.dataset.showcaseJump || 0);
    window.setTimeout(function () {
      var button = document.querySelector('[data-slide-target="' + index + '"]');
      if (button) button.click();
    }, 120);
  }

  document.querySelectorAll("[data-showcase]").forEach(function (showcase) {
    var track = showcase.querySelector(".feature-track");
    var buttons = Array.prototype.slice.call(showcase.querySelectorAll("[data-slide-target]"));
    var privacyButton = showcase.querySelector("[data-privacy-jump]");
    var slides = Array.prototype.slice.call(showcase.querySelectorAll(".feature-slide"));
    if (!track || !buttons.length || !slides.length) return;

    var pendingIndex = null;
    var settleTimer = null;
    var privacyJumpActive = false;

    function setActive(index) {
      var slide = slides[index];
      if (!slide) return;
      privacyJumpActive = false;

      buttons.forEach(function (button, buttonIndex) {
        var active = buttonIndex === index;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });

      if (privacyButton) {
        privacyButton.classList.remove("is-active");
        privacyButton.setAttribute("aria-selected", "false");
      }
    }

    function syncFromScroll() {
      if (privacyJumpActive) return;
      var index = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
      index = Math.max(0, Math.min(slides.length - 1, index));
      setActive(index);
    }

    function activate(index, shouldScroll) {
      var slide = slides[index];
      if (!slide) return;

      setActive(index);

      if (shouldScroll) {
        pendingIndex = index;
        window.clearTimeout(settleTimer);
        track.scrollTo({
          left: slide.offsetLeft - track.offsetLeft,
          behavior: "smooth"
        });
      }
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var index = Number(button.dataset.slideTarget || 0);
        activate(index, true);
      });
    });

    if (privacyButton) {
      privacyButton.addEventListener("click", function () {
        buttons.forEach(function (button) {
          button.classList.remove("is-active");
          button.setAttribute("aria-selected", "false");
        });
        privacyJumpActive = true;
        pendingIndex = null;
        window.clearTimeout(settleTimer);
        track.scrollTo({ left: track.scrollLeft, behavior: "auto" });
        privacyButton.classList.add("is-active");
        privacyButton.setAttribute("aria-selected", "true");
        scrollToHash("#privacy-promise");
      });
    }

    var ticking = false;
    track.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        if (pendingIndex !== null) {
          setActive(pendingIndex);
          window.clearTimeout(settleTimer);
          settleTimer = window.setTimeout(function () {
            pendingIndex = null;
            syncFromScroll();
          }, 140);
        } else {
          syncFromScroll();
        }
        ticking = false;
      });
    }, { passive: true });
  });

  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      var hash = link.getAttribute("href");
      if (!scrollToHash(hash)) return;
      event.preventDefault();
      window.history.pushState(null, "", hash);
      jumpShowcase(link);
    });
  });

  if (window.location.hash) {
    settleHashPosition();
    window.addEventListener("load", settleHashPosition, { once: true });
  }

  if (/^(localhost|127\.0\.0\.1)$/.test(window.location.hostname)) {
    return;
  }

  fetch("/update.json")
    .then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    })
    .then(function (update) {
      if (!update || !update.latest) return;

      document.querySelectorAll(".js-ver").forEach(function (element) {
        element.textContent = "最新版 V" + String(update.latest).replace(/^v/i, "");
      });

      if (update.url) {
        document.querySelectorAll(".js-dl").forEach(function (element) {
          element.href = update.url;
        });
      }
    })
    .catch(function () {
      // Keep the static fallback copy when previewing locally or offline.
    });
})();
