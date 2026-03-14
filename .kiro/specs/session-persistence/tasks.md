# Implementation Plan: Session Persistence

## Overview

Add session persistence across three layers: extension-side (workspaceState for sessionId and chat history), webview-side (setState/getState for messages across visibility changes), and server-side (JSON file for AgentSession data across restarts). On panel restore, the extension validates the stored session against the server and gracefully handles missing sessions.

## Tasks

- [ ] 1. Extend vscode mock with workspaceState support
  - [ ] 1.1 Add `workspaceState` mock to `vscode-extension/src/__mocks__/vscode.ts`
    - Add `workspaceState` object with `get(key, defaultValue?)` and `update(key, value)` as `jest.fn()` mocks
    - Back with a simple `Map` so `get` returns previously `update`d values
    - Add `workspaceState` to the `ExtensionContext` mock if not already present
    - _Requirements: 1.1, 1.2, 3.1, 3.2_

- [ ] 2. Add session persistence methods to ChatPanel
  - [ ] 2.1 Update `ChatPanel` constructor to accept `ExtensionContext` in `vscode-extension/src/chatPanel.ts`
    - Add `private readonly context: vscode.ExtensionContext` parameter
    - Store reference for workspaceState access
    - _Requirements: 1.1, 1.2, 3.1_
  - [ ] 2.2 Add `persistSessionId`, `restoreSessionId` private methods
    - `persistSessionId(sessionId)`: calls `this.context.workspaceState.update('agent.sessionId', sessionId)`
    - `restoreSessionId()`: calls `this.context.workspaceState.get<string>('agent.sessionId')`, returns `string | undefined`
    - _Requirements: 1.1, 1.2_
  - [ ] 2.3 Add `persistMessage`, `loadChatHistory`, `clearChatHistory` private methods
    - `persistMessage(role, content)`: reads current array from workspaceState key `agent.chatHistory`, appends `{ role, content }`, writes back
    - `loadChatHistory()`: reads array from workspaceState, returns `ChatMessage[]` or empty array if missing/invalid
    - `clearChatHistory()`: sets `agent.chatHistory` to `[]` in workspaceState
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [ ] 2.4 Update `sendMessage` to persist sessionId and messages
    - After receiving response, call `this.persistSessionId(response.session_id)`
    - Call `this.persistMessage('user', text)` before sending to server
    - If no stored sessionId exists (new session), call `this.clearChatHistory()` before the first message
    - _Requirements: 1.1, 1.3, 3.1, 3.4_
  - [ ] 2.5 Update `addMessage` to persist messages for agent/system roles
    - Call `this.persistMessage(role, content)` for agent and system messages
    - Avoid double-persisting user messages (already persisted in sendMessage)
    - _Requirements: 3.1, 3.3_
  - [ ] 2.6 Write property test: Session ID round-trip through workspaceState (Property 1)
    - **Property 1: Session ID round-trip through workspaceState**
    - For any valid UUID string, `persistSessionId(id)` then `restoreSessionId()` returns the same string
    - File: `vscode-extension/src/__tests__/chatPanel.property.test.ts`
    - **Validates: Requirements 1.1, 1.2**
  - [ ] 2.7 Write property test: Chat history append preserves order and content (Property 2)
    - **Property 2: Chat history append preserves order and content**
    - For any sequence of N messages, after appending each, `loadChatHistory()` returns N messages in same order with identical fields
    - File: `vscode-extension/src/__tests__/chatPanel.property.test.ts`
    - **Validates: Requirements 3.1, 3.2, 3.3**
  - [ ] 2.8 Write property test: Session ID persistence is idempotent (Property 5)
    - **Property 5: Session ID persistence is idempotent**
    - For any session ID, calling `persistSessionId(id)` K times produces the same `restoreSessionId()` result as calling it once
    - File: `vscode-extension/src/__tests__/chatPanel.property.test.ts`
    - **Validates: Requirements 1.1**
  - [ ] 2.9 Write property test: Chat history clear produces empty state (Property 6)
    - **Property 6: Chat history clear produces empty state**
    - For any non-empty chat history, `clearChatHistory()` then `loadChatHistory()` returns empty array
    - File: `vscode-extension/src/__tests__/chatPanel.property.test.ts`
    - **Validates: Requirements 3.4**

- [ ] 3. Add session validation and restore logic to ChatPanel
  - [ ] 3.1 Add `validateSession` private method to `ChatPanel`
    - Call `this.agentClient.getStatus(sessionId)`
    - On success: return the `StatusResponse`
    - On 404 error: clear sessionId and chatHistory from workspaceState, return `null`
    - On connection error (ECONNREFUSED, ETIMEDOUT): log warning, return `null` without clearing state
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ] 3.2 Add `restoreSession` private method to `ChatPanel`
    - Call `restoreSessionId()` to get stored sessionId
    - If sessionId exists, call `validateSession(sessionId)`
    - If validation succeeds: set `this.sessionId`, load chat history, send messages to webview, start polling if status is "planning" or "executing"
    - If validation returns null (404): do nothing (state already cleared)
    - If validation returns null (connection error): set `this.sessionId` from stored value, load and display chat history anyway
    - If no stored sessionId: do nothing
    - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.2_
  - [ ] 3.3 Update `resolveWebviewView` to call `restoreSession`
    - After setting up webview HTML and message handlers, call `void this.restoreSession()`
    - _Requirements: 1.2, 2.1_
  - [ ] 3.4 Write unit tests for session validation and restore in `vscode-extension/src/__tests__/chatPanel.persistence.test.ts`
    - Test: valid server session restores chat history and starts polling for active session
    - Test: valid server session with completed status restores history but does not start polling
    - Test: server returns 404 clears workspaceState
    - Test: server unreachable retains stored sessionId and still shows chat history
    - Test: no stored sessionId skips validation entirely
    - Test: new message persists sessionId to workspaceState
    - Test: addMessage appends to chat history in workspaceState
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3_

- [ ] 4. Update webview HTML/JS for message state persistence
  - [ ] 4.1 Update webview script in `getHtmlForWebview` to save messages to webview state
    - In the `addMessage` case handler, after rendering the message, save the messages array to `vscode.setState({ messages })`
    - Maintain a local `messages` array in the script scope that accumulates all rendered messages
    - _Requirements: 4.1_
  - [ ] 4.2 Update webview script to restore messages from state on init
    - On script initialization, call `vscode.getState()` and check for a `messages` array
    - If present, iterate and render each message using the existing `renderContent` function
    - _Requirements: 4.2_
  - [ ] 4.3 Add `restoreMessages` and `clearMessages` message handlers to webview script
    - `restoreMessages`: receives an array of `{ role, content }` from the extension host, renders them and saves to webview state
    - `clearMessages`: clears the messages container DOM, resets the local messages array, and calls `setState({ messages: [] })`
    - _Requirements: 3.2, 4.2_
  - [ ] 4.4 Write property test: Webview state round-trip (Property 3)
    - **Property 3: Webview state round-trip**
    - For any array of messages stored via `setState({ messages })`, `getState().messages` returns an array with same length, roles, and content
    - File: `vscode-extension/src/__tests__/chatPanel.property.test.ts`
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [ ] 5. Update extension.ts to pass ExtensionContext to ChatPanel
  - [ ] 5.1 Update `ChatPanel` constructor call in `vscode-extension/src/extension.ts`
    - Change `new ChatPanel(context.extensionUri, agentClient)` to `new ChatPanel(context.extensionUri, agentClient, context)`
    - _Requirements: 1.1, 1.2_

- [ ] 6. Checkpoint - Verify extension-side persistence
  - Run all extension tests and verify they pass. Ask the user if questions arise.

- [ ] 7. Create server-side SessionStore module
  - [ ] 7.1 Create `server/session_store.py` with `SessionStore` class
    - `__init__(self, store_path: str = "data/sessions.json")`: store the path, create parent directory if needed
    - `serialize_session(self, session: AgentSession) -> dict`: convert AgentSession (and nested Plan, Task, ExecutionResult, FileChange) to JSON-serializable dict, converting enums to `.value`, datetimes to `.isoformat()`
    - `deserialize_session(self, data: dict) -> AgentSession`: reconstruct AgentSession from dict, parsing enum values and ISO datetime strings
    - `save(self, sessions: Dict[str, AgentSession]) -> None`: serialize all sessions, write JSON to file with `{"sessions": {...}, "version": 1}` format, wrap in try/except for IOError
    - `load(self) -> Dict[str, AgentSession]`: read JSON file, deserialize sessions, return dict. Return empty dict if file missing, corrupt, or invalid. Log warning on errors.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - [ ] 7.2 Write property test: Server session serialization round-trip (Property 4)
    - **Property 4: Server session serialization round-trip**
    - For any valid AgentSession (with optional Plan, ExecutionResult, FileChanges), `deserialize_session(serialize_session(session))` produces an equivalent AgentSession
    - Use hypothesis strategies for all nested dataclasses and enums
    - File: `tests/test_session_store_property.py`
    - **Validates: Requirements 5.1, 5.2, 5.3**
  - [ ] 7.3 Write property test: Corrupt session file produces empty sessions (Property 7)
    - **Property 7: Corrupt session file produces empty sessions**
    - For any non-JSON string written to the store file, `load()` returns an empty dict without raising
    - File: `tests/test_session_store_property.py`
    - **Validates: Requirements 5.4**
  - [ ] 7.4 Write unit tests for SessionStore in `tests/test_session_store.py`
    - Test: save and load round-trip with a session containing plan and execution result
    - Test: load from nonexistent file returns empty dict
    - Test: load from corrupt file returns empty dict and logs warning
    - Test: save creates data directory if missing
    - Test: save with IOError logs error and does not crash
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 8. Integrate SessionStore into server API
  - [ ] 8.1 Update `server/api.py` startup to load sessions from SessionStore
    - Import `SessionStore` from `server.session_store`
    - Add global `session_store: Optional[SessionStore] = None`
    - In `startup_event`, initialize `SessionStore` with path from config (default `data/sessions.json`)
    - Call `session_store.load()` and assign to `sessions` dict
    - _Requirements: 5.2, 5.5_
  - [ ] 8.2 Add `persist_sessions()` helper and call after session mutations in `server/api.py`
    - Add `persist_sessions()` function that calls `session_store.save(sessions)` if store is initialized
    - Call `persist_sessions()` at the end of `process_prompt`, `apply_changes`, `cancel_session`, and `notify_applied` endpoints
    - _Requirements: 5.1_
  - [ ] 8.3 Write property test: Session resume preserves state (Property 8)
    - **Property 8: Session resume preserves session state**
    - For any AgentSession, serialize to store, load back, extract status response fields — they match the original session's state
    - File: `tests/test_session_store_property.py`
    - **Validates: Requirements 6.1, 6.2**
  - [ ] 8.4 Write integration test for session persistence across simulated restart in `tests/test_session_persistence_integration.py`
    - Use FastAPI TestClient to create a session via POST /agent/prompt (mocking LLM/executor)
    - Verify session accessible via GET /agent/status
    - Clear in-memory sessions dict, call `session_store.load()` to repopulate
    - Verify session still accessible via GET /agent/status with same data
    - _Requirements: 5.1, 5.2, 6.1, 6.2_

- [ ] 9. Checkpoint - Verify server-side persistence
  - Run all server tests and verify they pass. Ask the user if questions arise.

- [ ] 10. Final checkpoint - Full integration verification
  - Run all extension and server tests together. Verify no regressions in existing test suites.

## Notes

- Each task references specific requirements for traceability
- Property-based tests use fast-check (TypeScript) and hypothesis (Python)
- Extension property tests go in `vscode-extension/src/__tests__/chatPanel.property.test.ts`
- Server property tests go in `tests/test_session_store_property.py`
- The `data/` directory for session storage should be added to `.gitignore`
- The existing `agentClient.getStatus` method is reused for session validation — no new endpoint needed
