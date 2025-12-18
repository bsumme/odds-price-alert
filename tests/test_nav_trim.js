const assert = require('assert');
const path = require('path');

const navTrim = require(path.join('..', 'frontend', 'nav-trim.js'));

const createMobileWindow = (pathname, replace = () => {
    throw new Error('replace should not be called for allowed paths');
}) => {
    const navigator = {
        userAgent: 'iphone',
        vendor: '',
        maxTouchPoints: 1,
    };

    const window = {
        navigator,
        location: {
            pathname,
            search: '',
            hash: '',
            replace,
        },
        innerWidth: 800,
    };

    window.navigator = navigator;
    return { window, navigator };
};

const { window: nestedSettingsWindow, navigator: nestedSettingsNavigator } = createMobileWindow('/frontend/settings.html');

global.window = nestedSettingsWindow;
global.navigator = nestedSettingsNavigator;
global.document = undefined;

assert.strictEqual(navTrim.normalizePathname('/frontend/settings.html'), '/settings', 'normalizePathname should strip nested settings path');
assert.strictEqual(navTrim.enforceMobileMainPage(), true, 'enforceMobileMainPage should allow nested settings path');

const { window: mobileFolderWindow, navigator: mobileFolderNavigator } = createMobileWindow('/mobile/BestValueBetMobile.html');

global.window = mobileFolderWindow;
global.navigator = mobileFolderNavigator;
global.document = undefined;

assert.strictEqual(navTrim.enforceMobileMainPage(), true, 'enforceMobileMainPage should allow mobile folder pages');

let redirectedTo = null;
const { window: desktopWindow, navigator: desktopNavigator } = createMobileWindow(
    '/BensSportsBookApp.html',
    (destination) => {
        redirectedTo = destination;
    }
);

global.window = desktopWindow;
global.navigator = desktopNavigator;
global.document = undefined;

assert.strictEqual(navTrim.enforceMobileMainPage(), false, 'enforceMobileMainPage should block desktop pages on mobile');
assert.strictEqual(
    redirectedTo,
    `${navTrim.mobileMainPage}`,
    'enforceMobileMainPage should redirect desktop pages to the mobile main page'
);

console.log('All nav-trim tests passed');
