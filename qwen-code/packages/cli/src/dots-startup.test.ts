/**
 * @license
 * Copyright 2026 Qwen Team
 * SPDX-License-Identifier: Apache-2.0
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  config: vi.fn(),
  shutdown: vi.fn(),
  start: vi.fn(),
  cleanup: vi.fn(),
  loadSettings: vi.fn(),
}));

vi.mock('@qwen-code/qwen-code-core/config/config.js', () => ({
  Config: class {
    constructor(parameters: unknown) {
      mocks.config(parameters);
    }
    shutdown = mocks.shutdown;
  },
}));
vi.mock('@qwen-code/qwen-code-core/tools/tool-names.js', () => ({
  ToolNames: { SHELL: 'run_shell_command', READ: 'read_file' },
}));
vi.mock('./config/settings.js', () => ({
  loadSettings: mocks.loadSettings,
  LoadedSettings: class {
    merged: unknown;
    constructor(
      _system: unknown,
      _defaults: unknown,
      user: { settings: unknown },
    ) {
      this.merged = user.settings;
    }
  },
}));
vi.mock('./core/theme.js', () => ({ validateTheme: () => null }));
vi.mock('./i18n/index.js', () => ({
  initializeI18n: vi.fn(),
  resolveLanguageSetting: () => 'en',
}));
vi.mock('./ui/themes/theme-manager.js', () => ({
  themeManager: { setActiveTheme: vi.fn() },
}));
vi.mock('./ui/startInteractiveUI.js', () => ({
  startInteractiveUI: mocks.start,
}));
vi.mock('./utils/cleanup.js', () => ({
  registerCleanup: mocks.cleanup,
  runExitCleanup: vi.fn(),
}));

import { runDotsCli } from './dots-startup.js';

describe('Dots startup', () => {
  const stdinTTY = Object.getOwnPropertyDescriptor(process.stdin, 'isTTY');
  const stdoutTTY = Object.getOwnPropertyDescriptor(process.stdout, 'isTTY');
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(process, 'once').mockReturnValue(process);
    Object.defineProperty(process.stdin, 'isTTY', {
      configurable: true,
      value: true,
    });
    Object.defineProperty(process.stdout, 'isTTY', {
      configurable: true,
      value: true,
    });
    mocks.loadSettings.mockReturnValue({
      merged: {
        ui: { theme: 'Default' },
        security: { auth: { selectedType: 'qwen-oauth' } },
      },
      user: { path: '/tmp/dots-test-settings.json' },
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    for (const [stream, descriptor] of [
      [process.stdin, stdinTTY],
      [process.stdout, stdoutTTY],
    ] as const) {
      if (descriptor) Object.defineProperty(stream, 'isTTY', descriptor);
      else Reflect.deleteProperty(stream, 'isTTY');
    }
  });

  it('starts the upstream TUI without inheriting local provider or tool settings', async () => {
    await runDotsCli();
    expect(mocks.config).toHaveBeenCalledWith(
      expect.objectContaining({
        safeMode: true,
        bareMode: true,
        excludeTools: ['run_shell_command', 'read_file'],
        disableAllHooks: true,
        chatRecording: false,
        cronEnabled: false,
        telemetry: { enabled: false },
      }),
    );
    const settings = mocks.start.mock.calls[0][1];
    expect(settings.merged.security).toBeUndefined();
    expect(settings.merged.general.enableAutoUpdate).toBe(false);
    expect(settings.merged.ui.enableFollowupSuggestions).toBe(false);
    expect(mocks.start.mock.calls[0][4]).toEqual({
      authError: null,
      shouldOpenAuthDialog: false,
      themeError: null,
      memoryFileCount: 0,
    });
  });
});
