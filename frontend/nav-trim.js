(() => {
    const mobileMainPage = "/market-hub.html";
    const hiddenNavTargets = ["/watcher.html", "/linetracker.html", "/value.html"];

    const isMobileDevice = () => {
        const userAgent = navigator.userAgent || navigator.vendor || window.opera || "";
        const mobileRegex = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i;
        const isSmallScreen = window.innerWidth < 900;
        const hasTouchScreen = "ontouchstart" in window || navigator.maxTouchPoints > 0;

        return mobileRegex.test(userAgent.toLowerCase()) || (isSmallScreen && hasTouchScreen);
    };

    const enforceMobileMainPage = () => {
        if (!isMobileDevice()) return true;

        const pathname = window.location.pathname || "";
        const onMainPage = pathname.endsWith(mobileMainPage) || pathname === "/";

        if (onMainPage) return true;

        const destination = `${mobileMainPage}${window.location.search || ""}${window.location.hash || ""}`;
        window.location.replace(destination);
        return false;
    };

    const shouldHideLink = (href = "") => hiddenNavTargets.some((target) => href.endsWith(target));

    const stripHiddenToolbarLinks = () => {
        document.querySelectorAll('header nav a').forEach((link) => {
            if (shouldHideLink(link.getAttribute('href') || link.dataset.href)) {
                link.remove();
            }
        });
    };

    const initialize = () => {
        if (!enforceMobileMainPage()) return;
        stripHiddenToolbarLinks();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();
