import * as vscode from 'vscode';
import { AgentStatusBar } from '../statusBar';

const mockCreateStatusBarItem = vscode.window.createStatusBarItem as jest.Mock;

describe('AgentStatusBar', () => {
  let statusBar: AgentStatusBar;
  let mockItem: {
    text: string;
    command: string;
    tooltip: string;
    show: jest.Mock;
    hide: jest.Mock;
    dispose: jest.Mock;
  };

  beforeEach(() => {
    jest.clearAllMocks();
    statusBar = new AgentStatusBar();
    mockItem = mockCreateStatusBarItem.mock.results[0].value;
  });

  describe('constructor', () => {
    it('creates a status bar item with Left alignment and priority 100', () => {
      expect(mockCreateStatusBarItem).toHaveBeenCalledWith(
        vscode.StatusBarAlignment.Left,
        100
      );
    });

    it('sets command to local-agent.openChat', () => {
      expect(mockItem.command).toBe('local-agent.openChat');
    });

    it('initial state is idle', () => {
      expect(statusBar.getState()).toBe('idle');
    });

    it('shows the status bar item on creation', () => {
      expect(mockItem.show).toHaveBeenCalled();
    });

    it('initial text contains Idle', () => {
      expect(mockItem.text).toContain('Idle');
    });
  });

  describe('setState', () => {
    it('sets idle state text and tooltip', () => {
      statusBar.setState('executing');
      statusBar.setState('idle');
      expect(mockItem.text).toContain('Idle');
      expect(mockItem.tooltip).toBeTruthy();
    });

    it('sets planning state text and tooltip', () => {
      statusBar.setState('planning');
      expect(mockItem.text).toContain('Planning');
      expect(mockItem.tooltip).toBeTruthy();
    });

    it('sets executing state text and tooltip', () => {
      statusBar.setState('executing');
      expect(mockItem.text).toContain('Executing');
      expect(mockItem.tooltip).toBeTruthy();
    });

    it('sets error state text and tooltip', () => {
      statusBar.setState('error');
      expect(mockItem.text).toContain('Error');
      expect(mockItem.tooltip).toBeTruthy();
    });
  });

  describe('setProgress', () => {
    it('sets text to contain the progress percentage', () => {
      statusBar.setProgress(42);
      expect(mockItem.text).toContain('42%');
    });

    it('handles 100% progress', () => {
      statusBar.setProgress(100);
      expect(mockItem.text).toContain('100%');
    });

    it('handles 0% progress', () => {
      statusBar.setProgress(0);
      expect(mockItem.text).toContain('0%');
    });

    it('sets tooltip to task description when provided', () => {
      statusBar.setProgress(50, 'Building files');
      expect(mockItem.tooltip).toBe('Building files');
    });

    it('sets default tooltip when no description provided', () => {
      statusBar.setProgress(50);
      expect(mockItem.tooltip).toContain('50%');
    });
  });

  describe('getState', () => {
    it('returns idle initially', () => {
      expect(statusBar.getState()).toBe('idle');
    });

    it('returns executing after setState', () => {
      statusBar.setState('executing');
      expect(statusBar.getState()).toBe('executing');
    });
  });

  describe('dispose', () => {
    it('calls dispose on the status bar item', () => {
      statusBar.dispose();
      expect(mockItem.dispose).toHaveBeenCalled();
    });
  });
});
