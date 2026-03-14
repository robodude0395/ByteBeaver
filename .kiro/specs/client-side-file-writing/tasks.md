# Implementation Plan: Client-Side File Writing

## Overview

Move file writing from the agent server to the VSCode extension client. The `DiffProvider.acceptChanges()` method will write files locally using `vscode.workspace.fs` instead of delegating to the server's `apply_changes` endpoint. After local writes, the extension sends a fire-and-forget notification to the server for session state tracking. The server gets a new `/agent/notify_applied` endpoint.

## Tasks

- [x] 1. Extend vscode mock with workspace.fs methods
  - [x] 1.1 Add `workspace.fs` mock object to `vscode-extension/src/__mocks__/vscode.ts`
    - Add `writeFile`, `delete`, and `createDirectory` as `jest.fn()` mocks on `workspace.fs`
    - Ensure `writeFile` and `createDirectory` resolve by default, `delete` resolves by default
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 2.1, 2.2_

- [x] 2. Add `NotifyAppliedRequest` interface and `notifyChangesApplied` method to AgentClient
  - [x] 2.1 Add `NotifyAppliedRequest` interface and `notifyChangesApplied()` method to `vscode-extension/src/agentClient.ts`
    - Define `NotifyAppliedRequest` with `session_id: string` and `change_ids: string[]`
    - Implement `notifyChangesApplied(sessionId, changeIds)` that POSTs to `/agent/notify_applied`
    - Wrap in try/catch, log errors, never throw (fire-and-forget)
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 2.2 Write unit tests for `notifyChangesApplied` in `vscode-extension/src/__tests__/agentClient.test.ts`
    - Test successful notification call
    - Test that errors are caught and do not propagate
    - _Requirements: 3.1, 3.2_

- [x] 3. Rewrite `DiffProvider.acceptChanges()` for local file writing
  - [x] 3.1 Add `WriteResult` interface and `extractContent`, `ensureParentDirectories`, `applyChangeLocally` private methods to `DiffProvider` in `vscode-extension/src/diffProvider.ts`
    - `WriteResult`: `{ changeId: string; filePath: string; success: boolean; error?: string }`
    - `extractContent(change)`: encode `change.diff` to `Uint8Array` via `TextEncoder`
    - `ensureParentDirectories(fileUri)`: call `vscode.workspace.fs.createDirectory` on parent URI with `{ recursive: true }`
    - `applyChangeLocally(workspaceRoot, change)`: resolve path via `Uri.joinPath`, handle create/modify (ensureParentDirectories + writeFile) and delete (fs.delete), return `WriteResult`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 5.2, 6.1, 6.2_
  - [x] 3.2 Rewrite `acceptChanges()` in `DiffProvider`
    - Validate workspace folder is open; if not, show error and return
    - Loop through all pending changes, call `applyChangeLocally` for each, collect `WriteResult[]`
    - Display summary: all success → info message, partial failure → warning with counts and failed paths, all failed → error message
    - Call `agentClient.notifyChangesApplied()` with successfully applied change IDs (fire-and-forget)
    - Clear pending changes, session, content provider, and hide status bar buttons in finally block
    - _Requirements: 1.1, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1, 7.4_
  - [x] 3.3 Write property test: Local writes bypass server apply_changes (Property 1)
    - **Property 1: Local writes bypass server apply_changes**
    - For any set of pending changes, `acceptChanges()` calls `vscode.workspace.fs.writeFile`/`delete` and never calls `agentClient.applyChanges`
    - **Validates: Requirements 1.1**
  - [x] 3.4 Write property test: File paths resolve against workspace root (Property 2)
    - **Property 2: File paths resolve against workspace root**
    - For any `FileChangeInfo` with a relative `file_path`, the URI passed to `writeFile`/`delete` equals `Uri.joinPath(workspaceRoot, file_path)`
    - **Validates: Requirements 1.2, 5.2**
  - [x] 3.5 Write property test: Create and modify writes use diff content (Property 3)
    - **Property 3: Create and modify writes use diff content**
    - For any `FileChangeInfo` with `change_type` "create" or "modify", `writeFile` is called with the `diff` field encoded as `Uint8Array`
    - **Validates: Requirements 1.3, 1.4**
  - [x] 3.6 Write property test: Delete removes the file (Property 4)
    - **Property 4: Delete removes the file**
    - For any `FileChangeInfo` with `change_type` "delete", `vscode.workspace.fs.delete` is called with the resolved URI
    - **Validates: Requirements 1.5**
  - [x] 3.7 Write property test: Parent directories are created (Property 5)
    - **Property 5: Parent directories are created for nested paths**
    - For any `FileChangeInfo` with directory separators in `file_path`, `createDirectory` is called with the parent URI before `writeFile`
    - **Validates: Requirements 2.1**
  - [x] 3.8 Write property test: Content round-trip fidelity (Property 9)
    - **Property 9: Content round-trip fidelity**
    - For any valid `FileChangeInfo`, `new TextDecoder().decode(extractContent(change)) === change.diff`
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Update existing DiffProvider tests for local write behavior
  - [x] 5.1 Update `vscode-extension/src/__tests__/diffProvider.test.ts` to reflect new `acceptChanges` behavior
    - Replace tests that assert `agentClient.applyChanges` calls with tests asserting `vscode.workspace.fs.writeFile`/`delete` calls
    - Add test: workspace validation — no workspace folder open shows error and aborts
    - Add test: server notification failure does not affect user-facing success
    - Add test: all writes fail shows error message
    - Add test: single write failure in batch shows warning with failed path
    - Add test: empty pending changes returns immediately
    - Add test: delete change type calls `vscode.workspace.fs.delete`
    - _Requirements: 1.1, 4.1, 4.2, 4.3, 4.4, 5.1, 7.4_
  - [x] 5.2 Write property test: Server notified with applied change IDs (Property 6)
    - **Property 6: Server is notified with applied change IDs**
    - For any batch where at least one write succeeds, `notifyChangesApplied` is called with the successful change IDs
    - **Validates: Requirements 3.1**
  - [x] 5.3 Write property test: Partial failures do not abort the batch (Property 7)
    - **Property 7: Partial failures do not abort the batch**
    - For any batch of N changes where K fail, all N are attempted and N-K succeed
    - **Validates: Requirements 4.2**
  - [x] 5.4 Write property test: Summary message reflects actual counts (Property 8)
    - **Property 8: Summary message reflects actual counts**
    - For any batch with S successes and F failures, the displayed message contains both counts
    - **Validates: Requirements 4.3**
  - [x] 5.5 Write property test: Reject clears state without writing (Property 10)
    - **Property 10: Reject clears state without writing**
    - For any pending changes, `rejectChanges()` clears state and makes zero `writeFile`/`delete` calls
    - **Validates: Requirements 7.3**
  - [x] 5.6 Write property test: Accept clears state after writing (Property 11)
    - **Property 11: Accept clears state after writing**
    - After `acceptChanges()`, `getPendingChanges()` returns empty and status bar buttons are hidden
    - **Validates: Requirements 7.4**

- [x] 6. Add server-side `/agent/notify_applied` endpoint
  - [x] 6.1 Add `NotifyAppliedRequest` Pydantic model and `POST /agent/notify_applied` endpoint to `server/api.py`
    - Define `NotifyAppliedRequest` with `session_id: str` and `change_ids: list[str]`
    - Implement endpoint that finds the session, marks matching `FileChange` objects as `applied = True`
    - Return 404 if session not found, 200 with count of marked changes on success
    - _Requirements: 3.1_
  - [x] 6.2 Write unit tests for `/agent/notify_applied` in `tests/`
    - Test successful notification marks changes as applied
    - Test 404 for unknown session
    - Test with change IDs that don't match any changes (no error, just zero marked)
    - _Requirements: 3.1_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property-based tests use fast-check (TypeScript) and hypothesis (Python)
- Property tests should be placed in `vscode-extension/src/__tests__/diffProvider.property.test.ts`
- The existing `agentClient.applyChanges` method is kept for backward compatibility but is no longer called from `acceptChanges()`
