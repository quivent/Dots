/**
 * @license
 * Copyright 2026 Dots contributors
 * SPDX-License-Identifier: Apache-2.0
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PartListUnion } from '@google/genai';
import type { useLlmStream } from './use-llm-stream.js';
import { MessageType, StreamingState } from '../types.js';
import {
  getDotsBackend,
  type DotSnapshot,
} from '../../services/dots-backend.js';

interface DotStatus extends DotSnapshot {
  tasks?: Array<{
    title?: string;
    id?: string;
    status?: string;
    state?: string;
  }>;
  task_error?: string;
}

export function dotsStatusText(status: DotStatus): string {
  const lines = [
    status.name,
    `Runtime: ${status.profile.is_paused ? 'Paused' : 'Active'}`,
    `Delivery: ${status.pending ? 'Pending · /wait to check' : 'No pending message'}`,
  ];
  if (status.profile['last_check_in_at'])
    lines.push(`Last check-in: ${status.profile['last_check_in_at']}`);
  for (const task of status.tasks || [])
    lines.push(
      `${task.title || task.id || 'Task'} · ${task.status || task.state || 'Unknown'}`,
    );
  if (status.task_error) lines.push(`Tasks unavailable: ${status.task_error}`);
  return lines.join('\n');
}

export function dotsMessageText(query: PartListUnion): string {
  if (typeof query === 'string') return query;
  const parts = Array.isArray(query) ? query : [query];
  return parts
    .map((part) => {
      if (typeof part === 'string') return part;
      if (typeof part.text !== 'string') {
        throw new Error('Dot messaging currently accepts text only.');
      }
      return part.text;
    })
    .join('');
}

export function useDotsStream(
  ...args: Parameters<typeof useLlmStream>
): ReturnType<typeof useLlmStream> {
  const [, , addItem, , , , , , , , , , , , refreshStatic] = args;
  const updateItem = args[25];
  const [streamingState, setStreamingState] = useState(StreamingState.Idle);
  const [initError, setInitError] = useState<string | null>(null);
  const streamingResponseLengthRef = useRef(0);
  const ready = useRef(false);
  const busy = useRef(false);
  const pending = useRef(false);
  const lastError = useRef('');
  const messages = useRef(new Map<string, { uiId: number; text: string }>());
  const callbacks = useRef({ addItem, updateItem, refreshStatic });
  callbacks.current = { addItem, updateItem, refreshStatic };

  const report = useCallback((error: unknown) => {
    const text = error instanceof Error ? error.message : String(error);
    if (text !== lastError.current) {
      callbacks.current.addItem({ type: MessageType.ERROR, text }, Date.now());
      lastError.current = text;
    }
  }, []);

  const reconcile = useCallback((snapshot: DotSnapshot) => {
    pending.current = snapshot.pending;
    setStreamingState(
      snapshot.pending ? StreamingState.Responding : StreamingState.Idle,
    );
    const present = new Set(snapshot.messages.map((message) => message.id));
    for (const [id, previous] of messages.current) {
      if (!present.has(id)) {
        callbacks.current.updateItem?.(previous.uiId, {
          text: '[Message deleted]',
        });
        messages.current.delete(id);
        callbacks.current.refreshStatic();
      }
    }
    for (const message of snapshot.messages) {
      if (!message.text) continue;
      const previous = messages.current.get(message.id);
      if (!previous) {
        const uiId = callbacks.current.addItem(
          {
            type: message.mine ? MessageType.USER : MessageType.GEMINI,
            text: message.text,
          },
          Date.now(),
        );
        messages.current.set(message.id, { uiId, text: message.text });
      } else if (previous.text !== message.text) {
        callbacks.current.updateItem?.(previous.uiId, { text: message.text });
        previous.text = message.text;
        callbacks.current.refreshStatic();
      }
    }
    lastError.current = '';
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const backend = getDotsBackend();
    const pollValue = Number(process.env['DOTS_POLL'] || 2);
    const poll =
      Number.isFinite(pollValue) && pollValue > 0 ? pollValue * 1000 : 2000;
    const receive = async () => {
      try {
        if (!busy.current) {
          const snapshot = await backend.request<DotSnapshot>('refresh');
          if (!stopped) reconcile(snapshot);
        }
      } catch (error) {
        if (!stopped) report(error);
      } finally {
        if (!stopped) timer = setTimeout(() => void receive(), poll);
      }
    };
    void backend
      .request<DotSnapshot>('connect', {
        dot: process.env['DOTS_DOT'] || undefined,
        by_id: process.env['DOTS_BY_ID'] === '1',
        source: process.env['DOTS_SOURCE'] || 'local',
      })
      .then((snapshot) => {
        if (stopped) return;
        ready.current = true;
        reconcile(snapshot);
        callbacks.current.addItem(
          {
            type: MessageType.INFO,
            text: `${snapshot.name} · ${snapshot.profile.is_paused ? 'Paused' : 'Connected'} · ChatGPT Dot`,
          },
          Date.now(),
        );
        timer = setTimeout(() => void receive(), poll);
      })
      .catch((error: unknown) => {
        if (stopped) return;
        setInitError(error instanceof Error ? error.message : String(error));
        report(error);
      });
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [reconcile, report]);

  const submitQuery: ReturnType<typeof useLlmStream>['submitQuery'] =
    useCallback(
      async (query) => {
        let text: string;
        try {
          text = dotsMessageText(query);
        } catch (error) {
          report(error);
          throw error;
        }
        if (!text.trim()) return;
        if (!ready.current) {
          const error = new Error('Dot is not connected.');
          report(error);
          throw error;
        }
        if (busy.current) {
          const error = new Error('A backend operation is still running.');
          report(error);
          throw error;
        }
        const command =
          !text.includes('\n') && !text.includes('\r') ? text.trim() : '';
        const backend = getDotsBackend();
        busy.current = true;
        try {
          if (command === '/status') {
            const status = await backend.request<DotStatus>('status');
            callbacks.current.addItem(
              { type: MessageType.INFO, text: dotsStatusText(status) },
              Date.now(),
            );
          } else if (command === '/refresh' || command === '/wait') {
            reconcile(await backend.request<DotSnapshot>('refresh'));
          } else if (command === '/abandon') {
            reconcile(await backend.request<DotSnapshot>('abandon'));
            callbacks.current.addItem(
              {
                type: MessageType.INFO,
                text: 'Stopped tracking. Delivery and cloud work have not been cancelled.',
              },
              Date.now(),
            );
          } else if (command.startsWith('/')) {
            callbacks.current.addItem(
              {
                type: MessageType.INFO,
                text: 'Commands: /refresh /wait /status /abandon /quit',
              },
              Date.now(),
            );
          } else {
            if (pending.current)
              throw new Error(
                'Previous message is pending. Use /wait or /abandon.',
              );
            setStreamingState(StreamingState.Responding);
            reconcile(await backend.request<DotSnapshot>('send', { text }));
          }
        } catch (error) {
          report(error);
          // A failed POST may still be accepted: recover its journal without resending.
          try {
            reconcile(await backend.request<DotSnapshot>('refresh'));
          } catch {
            setStreamingState(
              pending.current ? StreamingState.Responding : StreamingState.Idle,
            );
          }
          if (!command.startsWith('/')) throw error;
        } finally {
          busy.current = false;
        }
      },
      [reconcile, report],
    );

  return {
    streamingState,
    submitQuery,
    initError,
    pendingHistoryItems: [],
    clearPendingState: () => {},
    thought: null,
    cancelOngoingRequest: () => {
      report(
        new Error(
          'A cloud send cannot be cancelled here. /wait checks delivery; /abandon stops tracking.',
        ),
      );
      return false;
    },
    preemptGoalTurn: () => {},
    retryLastPrompt: async () => {
      await submitQuery('/wait');
    },
    pendingToolCalls: [],
    handleApprovalModeChange: async () => {},
    activePtyId: undefined,
    loopDetectionConfirmationRequest: null,
    streamingResponseLengthRef,
    isReceivingContent: false,
    workflowKeywordActive: false,
  };
}
