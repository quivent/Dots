/**
 * @license
 * Copyright 2026 Dots contributors
 * SPDX-License-Identifier: Apache-2.0
 */
// @vitest-environment jsdom

import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { useLlmStream } from './use-llm-stream.js';
import { dotsMessageText, useDotsStream } from './use-dots-stream.js';
import { StreamingState } from '../types.js';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('../../services/dots-backend.js', () => ({
  getDotsBackend: () => ({ request }),
}));

const snapshot = {
  name: 'Fixture',
  profile: { is_paused: false },
  pending: false,
  messages: [{ id: 'reply', text: 'Original reply', mine: false }],
};

function setup() {
  const addItem = vi.fn().mockReturnValue(42);
  const updateItem = vi.fn();
  const refreshStatic = vi.fn();
  const values: unknown[] = [];
  values[2] = addItem;
  values[14] = refreshStatic;
  values[25] = updateItem;
  const args = values as Parameters<typeof useLlmStream>;
  return {
    ...renderHook(() => useDotsStream(...args)),
    addItem,
    updateItem,
    refreshStatic,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue(snapshot);
});

describe('Dots conversation', () => {
  it('removes deleted provider content from the displayed transcript', async () => {
    const ui = setup();
    await waitFor(() => expect(ui.addItem).toHaveBeenCalled());
    request.mockResolvedValueOnce({ ...snapshot, messages: [] });
    await act(async () => {
      await ui.result.current.submitQuery('/refresh');
    });
    expect(ui.updateItem).toHaveBeenCalledWith(42, {
      text: '[Message deleted]',
    });
    expect(ui.refreshStatic).toHaveBeenCalled();
    ui.unmount();
  });
  it('sends only the submitted text and updates an existing reply', async () => {
    const ui = setup();
    await waitFor(() =>
      expect(ui.addItem).toHaveBeenCalledWith(
        expect.objectContaining({ text: 'Original reply' }),
        expect.any(Number),
      ),
    );
    request.mockResolvedValueOnce({
      ...snapshot,
      messages: [{ id: 'reply', text: 'Edited reply', mine: false }],
    });
    await act(async () => {
      await ui.result.current.submitQuery('Exact\nmessage');
    });
    expect(request.mock.calls.filter(([method]) => method === 'send')).toEqual([
      ['send', { text: 'Exact\nmessage' }],
    ]);
    expect(ui.updateItem).toHaveBeenCalledWith(42, { text: 'Edited reply' });
    expect(ui.refreshStatic).toHaveBeenCalled();
    ui.unmount();
  });

  it('recovers an uncertain send by reading without retrying it', async () => {
    const ui = setup();
    await waitFor(() => expect(ui.addItem).toHaveBeenCalled());
    request.mockRejectedValueOnce(new Error('Uncertain delivery'));
    request.mockResolvedValueOnce({ ...snapshot, pending: true });
    await act(async () => {
      await expect(ui.result.current.submitQuery('once')).rejects.toThrow(
        'Uncertain',
      );
    });
    expect(
      request.mock.calls.filter(([method]) => method === 'send'),
    ).toHaveLength(1);
    expect(request.mock.calls.at(-1)?.[0]).toBe('refresh');
    expect(ui.result.current.streamingState).toBe(StreamingState.Responding);
    await act(async () => {
      await expect(ui.result.current.submitQuery('again')).rejects.toThrow(
        'pending',
      );
    });
    expect(
      request.mock.calls.filter(([method]) => method === 'send'),
    ).toHaveLength(1);
    ui.unmount();
  });

  it('does not send unsupported slash commands or status checks', async () => {
    const ui = setup();
    await waitFor(() => expect(ui.addItem).toHaveBeenCalled());
    await act(async () => {
      await ui.result.current.submitQuery('/shell ls');
      await ui.result.current.submitQuery('/status');
    });
    expect(
      request.mock.calls.filter(([method]) => method === 'send'),
    ).toHaveLength(0);
    expect(request).toHaveBeenCalledWith('status');
    ui.unmount();
  });

  it('preserves multiline slash-prefixed messages and rejects nontext attachments', () => {
    expect(
      dotsMessageText([{ text: '/tmp/path\n' }, { text: 'second line' }]),
    ).toBe('/tmp/path\nsecond line');
    expect(() =>
      dotsMessageText([{ inlineData: { data: 'x', mimeType: 'image/png' } }]),
    ).toThrow('text only');
  });
});
