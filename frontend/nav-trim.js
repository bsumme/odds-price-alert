(() => {
    const hiddenNavTargets = ["/watcher.html", "/linetracker.html", "/value.html"];

    const shouldHideLink = (href = "") => hiddenNavTargets.some((target) => href.endsWith(target));

    const stripHiddenToolbarLinks = () => {
        document.querySelectorAll('header nav a').forEach((link) => {
            if (shouldHideLink(link.getAttribute('href') || link.dataset.href)) {
                link.remove();
            }
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", stripHiddenToolbarLinks);
    } else {
        stripHiddenToolbarLinks();
    }
})();
