# Frontend acceptance checks

The browser app is dependency-free. These development-only checks use Node's built-in test runner and the locked jsdom dependency. Use Node 20.19+, 22.13+ or 24+.

```sh
npm ci
npm run test:frontend
```

Run these commands from the repository root. They work in a standalone checkout and do not depend on other portfolio repositories. The equivalent direct test-runner command after installation is:

```sh
node --test frontend-tests/*.test.cjs
```

The suite verifies that absent measurements are not invented, submitted runs establish CSRF sessions, a failed held-out check is not shown as a solved task, backend content cannot inject HTML, rejected links cannot execute scripts, terminal run states are distinguished from active work, keyboard tabs expose one focus stop, and recorded Unix-second dates retain their year. No inference calls or paid requests are made.

Visual browser acceptance remains separate: inspect desktop and 320px/mobile layouts, all three views, patch/test/trace tabs, unavailable-provider mode, and a recorded run. This directory does not claim that a jsdom test verifies layout.
