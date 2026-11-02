/**
 * @license
 * Copyright 2026 Qwen Team
 * SPDX-License-Identifier: Apache-2.0
 */

import { Config } from '@qwen-code/qwen-code-core/config/config.js';
import { ToolNames } from '@qwen-code/qwen-code-core/tools/tool-names.js';
import { LoadedSettings, loadSettings } from './config/settings.js';
import type { Settings } from './config/settingsSchema.js';
import { validateTheme } from './core/theme.js';
import { initializeI18n, resolveLanguageSetting } from './i18n/index.js';
import { themeManager } from './ui/themes/theme-manager.js';
import { startInteractiveUI } from './ui/startInteractiveUI.js';
import { registerCleanup, runExitCleanup } from './utils/cleanup.js';

export async function runDotsCli(): Promise<void> {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error(
      'Dots interactive chat needs a terminal. Use dots chat --message TEXT.',
    );
  }
  const workspace = process.cwd();
  const saved = loadSettings(workspace);
  const presentation: Settings = {
    ui: {
      ...saved.merged.ui,
      hideTips: true,
      enableFollowupSuggestions: false,
      enableSpeculation: false,
    },
    general: {
      language: saved.merged.general?.language,
      vimMode: saved.merged.general?.vimMode,
      preferredEditor: saved.merged.general?.preferredEditor,
      enableAutoUpdate: false,
    },
    agents: { crossSessionMessaging: false },
  };
  const empty = { settings: {}, originalSettings: {}, path: '' };
  const settings = new LoadedSettings(
    empty,
    empty,
    {
      settings: presentation,
      originalSettings: presentation,
      path: saved.user.path,
    },
    empty,
    true,
    new Set(),
  );
  await initializeI18n(
    resolveLanguageSetting(presentation.general?.language as string),
  );
  if (presentation.ui?.theme)
    themeManager.setActiveTheme(presentation.ui.theme);
  const config = new Config({
    targetDir: workspace,
    cwd: workspace,
    model: 'ChatGPT Dot',
    debugMode: false,
    interactive: true,
    trustedFolder: true,
    safeMode: true,
    bareMode: true,
    coreTools: [],
    excludeTools: Object.values(ToolNames),
    mcpServers: {},
    disableAllHooks: true,
    accessibility: { enableLoadingPhrases: false },
    cronEnabled: false,
    chatRecording: false,
    usageStatisticsEnabled: false,
    telemetry: { enabled: false },
    enableManagedAutoMemory: false,
    enableManagedAutoDream: false,
    enableAutoSkill: false,
    enableTeamMemory: false,
    cliVersion: 'Dots',
  });
  registerCleanup(() => config.shutdown());
  const shutdown = () => {
    void runExitCleanup().then(() => process.exit(0));
  };
  process.once('SIGTERM', shutdown);
  await startInteractiveUI(
    config,
    settings,
    [],
    workspace,
    {
      authError: null,
      shouldOpenAuthDialog: false,
      themeError: validateTheme(settings),
      memoryFileCount: 0,
    },
    {
      postRenderConnectIde: false,
      postRenderInitializeTelemetry: false,
    },
  );
}
