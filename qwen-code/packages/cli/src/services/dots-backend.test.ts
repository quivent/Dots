/**
 * @license
 * Copyright 2026 Dots contributors
 * SPDX-License-Identifier: Apache-2.0
 */

import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock('node:child_process', () => ({ spawn }));
import { DotsBackend } from './dots-backend.js';

function worker() {
  const child = Object.assign(new EventEmitter(), {
    stdin: new PassThrough(),
    stdout: new PassThrough(),
    stderr: new PassThrough(),
  });
  spawn.mockReturnValue(child);
  return child;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe('Dots transport', () => {
  it('matches out-of-order replies without retrying sends', async () => {
    const child = worker();
    const lines: string[] = [];
    child.stdin.on('data', (data) => lines.push(String(data)));
    const backend = new DotsBackend();
    const first = backend.request('send', { text: 'one\nmessage' });
    const second = backend.request('status');
    expect(lines).toHaveLength(2);
    const sent = lines.map((line) => JSON.parse(line));
    child.stdout.write(
      JSON.stringify({ id: sent[1].id, result: 'status' }) + '\n',
    );
    child.stdout.write(
      JSON.stringify({ id: sent[0].id, result: 'accepted' }) + '\n',
    );
    await expect(first).resolves.toBe('accepted');
    await expect(second).resolves.toBe('status');
    expect(sent[0].params.text).toBe('one\nmessage');
    expect(lines).toHaveLength(2);
  });

  it('rejects pending requests on worker exit and never respawns it', async () => {
    const child = worker();
    const backend = new DotsBackend();
    const request = backend.request('send', { text: 'uncertain' });
    child.emit('exit', 1);
    await expect(request).rejects.toThrow('Dots backend exited');
    await expect(backend.request('send')).rejects.toThrow('closed');
    expect(spawn).toHaveBeenCalledTimes(1);
  });

  it('lets the worker finish before close resolves', async () => {
    const child = worker();
    const backend = new DotsBackend();
    const request = backend.request('send');
    child.stdout.write('{"id":1,"result":true}\n');
    await request;
    let closed = false;
    const closing = backend.close().then(() => {
      closed = true;
    });
    expect(child.stdin.writableEnded).toBe(true);
    expect(closed).toBe(false);
    child.emit('exit', 0);
    child.emit('close', 0);
    await closing;
    expect(closed).toBe(true);
  });
});
