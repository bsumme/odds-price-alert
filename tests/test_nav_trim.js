const assert = require('assert');
const path = require('path');

const navTrim = require(path.join('..', 'frontend', 'nav-trim.js'));

const createMobileWindow = (pathname) => {
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
            replace: () => {
                throw new Error('replace should not be called for allowed paths');
            },
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

console.log('All nav-trim tests passed');
