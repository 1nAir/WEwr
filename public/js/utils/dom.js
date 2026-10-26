/**
 * DOM Utilities & Lazy IntersectionObserver Wrapper.
 */

export function observeOnce(element, callback, rootMargin = '220px') {
  if (!element) return;
  if (!('IntersectionObserver' in window)) {
    callback();
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          observer.disconnect();
          callback();
          break;
        }
      }
    },
    { rootMargin }
  );

  observer.observe(element);
}

export function isMobileViewport() {
  return window.innerWidth <= 768;
}

