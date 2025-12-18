(() => {
    const mobileMainPage = "/ArbritrageBetFinder-mobile.html";
    const mobileFolderPrefix = "/mobile";
    const hiddenNavTargets = ["/watcher.html", "/linetracker.html", "/value.html"];
    const mobileAllowedPages = [
        mobileMainPage,
        "/sgp-builder.html",
        "/settings.html",
        "/settings",
        "/settings/",
    ];

    const isDebugNavEnabled = () => {
        try {
            const params = new URLSearchParams(window.location.search || "");
            const searchFlag = params.get("debug-nav");
            const localStorageFlag = window.localStorage?.getItem("debug-nav");

            return [searchFlag, localStorageFlag].some((value) => /^(1|true)$/i.test(value || ""));
        } catch (error) {
            return false;
        }
    };

    const debugLog = (...args) => {
        if (!isDebugNavEnabled()) return;
        console.log("[nav-trim]", ...args);
    };

    const isMobileDevice = () => {
        const userAgent = navigator.userAgent || navigator.vendor || window.opera || "";
        const mobileRegex = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i;
        const isSmallScreen = window.innerWidth < 900;
        const hasTouchScreen = "ontouchstart" in window || navigator.maxTouchPoints > 0;
        const matchesMobilePattern = mobileRegex.test(userAgent.toLowerCase());
        const isMobile = matchesMobilePattern || (isSmallScreen && hasTouchScreen);

        debugLog(
            "isMobileDevice inputs",
            { userAgent, isSmallScreen, hasTouchScreen, matchesMobilePattern },
            "->",
            isMobile
        );

        return isMobile;
    };

    const normalizePathname = (pathname = "") => {
        const trimmed = pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
        if (!trimmed || trimmed === "/") return "/";

        const lower = trimmed.toLowerCase();
        const withoutHtml = lower.replace(/\.html$/, "");
        const segments = withoutHtml.split("/");
        const lastSegment = segments[segments.length - 1];

        if (lastSegment === "settings") {
            return "/settings";
        }

        return withoutHtml;
    };

    const normalizeMobilePath = (pathname = "") => normalizePathname(pathname === "/" ? mobileMainPage : pathname);

    const normalizedMobileFolder = normalizePathname(mobileFolderPrefix);
    const normalizedMobileMainPage = normalizePathname(mobileMainPage);
    const allowedMobilePaths = new Set(mobileAllowedPages.map((page) => normalizePathname(page)));

    const isMobileFolderPath = (normalizedPath = "") =>
        normalizedPath === normalizedMobileFolder || normalizedPath.startsWith(`${normalizedMobileFolder}/`);

    const enforceMobileMainPage = () => {
        if (!isMobileDevice()) return true;

        const rawPathname = window.location.pathname || "";
        const normalizedPath = normalizeMobilePath(rawPathname);
        const onAllowedPage =
            normalizedPath === normalizedMobileMainPage ||
            allowedMobilePaths.has(normalizedPath) ||
            isMobileFolderPath(normalizedPath);

        debugLog("pathname", rawPathname, "normalized", normalizedPath, "onAllowedPage", onAllowedPage);

        if (onAllowedPage) {
            debugLog("enforceMobileMainPage allowing navigation");
            return true;
        }

        const destination = `${mobileMainPage}${window.location.search || ""}${window.location.hash || ""}`;
        debugLog("enforceMobileMainPage redirecting ->", destination);
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

    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            allowedMobilePaths,
            enforceMobileMainPage,
            initialize,
            isMobileFolderPath,
            isMobileDevice,
            mobileFolderPrefix,
            mobileAllowedPages,
            mobileMainPage,
            normalizeMobilePath,
            normalizePathname,
            stripHiddenToolbarLinks,
            shouldHideLink,
        };
    }

    if (typeof document !== "undefined") {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", initialize);
        } else {
            initialize();
        }
    }
})();
