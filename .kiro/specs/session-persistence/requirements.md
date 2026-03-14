# Requirements Document

## Introduction

Sessions in the local offline coding agent are currently ephemeral. On the extension side, the `sessionId` is held in memory on the `ChatPanel` instance and lost whenever the webview is disposed (user clicks away from the chat panel or restarts VS Code). On the server side, sessions live in an in-memory dictionary and are lost on server restart. Chat messages are rendered directly into the webview DOM with no persistence, so the conversation history disappears on every panel reload.

This feature adds persistence at three layers: the extension persists the session ID and chat history across panel lifecycle events, the webview preserves its rendered messages across visibility changes, and the server persists session state to disk so sessions survive server restarts.

## Glossary

- **Extension**: The VS Code extension host process that manages the ChatPanel, AgentClient, and DiffProvider
- **ChatPanel**: The Extension component implementing `WebviewViewProvider` that manages the chat UI and session state
- **Webview**: The HTML/JS panel rendered inside VS Code's sidebar, managed by ChatPanel
- **AgentClient**: The Extension component that communicates with the Agent_Server REST API
- **Agent_Server**: The remote FastAPI server that runs LLM inference and manages sessions
- **AgentSession**: The server-side dataclass holding session state (plan, execution result, status, timestamps)
- **Session_ID**: A UUID string that uniquely identifies an agent session
- **Workspace_State**: VS Code's `ExtensionContext.workspaceState` API, a per-workspace key-value store that persists across restarts
- **Webview_State**: The webview-local state managed via `acquireVsCodeApi().setState()` and `getState()`, persisted across visibility changes by VS Code
- **Chat_History**: An ordered list of message objects (role + content) representing the conversation in the chat panel
- **Session_Store**: A JSON file on the server's filesystem used to persist AgentSession data across server restarts

## Requirements

### Requirement 1: Extension-Side Session ID Persistence

**User Story:** As a developer, I want my session to continue when I click away from the chat panel and come back, so that I do not lose my conversation context.

#### Acceptance Criteria

1. WHEN the ChatPanel receives a Session_ID from the Agent_Server, THE Extension SHALL persist the Session_ID to Workspace_State
2. WHEN the ChatPanel's `resolveWebviewView` is called, THE Extension SHALL restore the Session_ID from Workspace_State
3. WHEN a restored Session_ID exists, THE Extension SHALL use the restored Session_ID in subsequent calls to `AgentClient.sendPrompt`
4. WHEN the user sends a new message and no Session_ID is stored, THE Extension SHALL allow the Agent_Server to create a new session

### Requirement 2: Session Validation on Restore

**User Story:** As a developer, I want the extension to verify that my previous session still exists on the server, so that I get a clean start if the server was restarted.

#### Acceptance Criteria

1. WHEN a Session_ID is restored from Workspace_State, THE Extension SHALL call `AgentClient.getStatus` to verify the session exists on the Agent_Server
2. IF the Agent_Server returns a 404 for the restored Session_ID, THEN THE Extension SHALL clear the stored Session_ID from Workspace_State and proceed without a session
3. IF the Agent_Server is unreachable during session validation, THEN THE Extension SHALL retain the stored Session_ID and attempt to use it on the next user message
4. WHEN session validation succeeds, THE Extension SHALL restore status polling if the session status is "planning" or "executing"
5. WHEN session validation succeeds and the session status is "completed", "error", or "cancelled", THE Extension SHALL not start status polling

### Requirement 3: Chat History Persistence in Extension

**User Story:** As a developer, I want my chat messages to be visible when I return to the chat panel, so that I can see the full conversation history.

#### Acceptance Criteria

1. WHEN a message is added to the chat (user, agent, or system role), THE ChatPanel SHALL append the message to Chat_History stored in Workspace_State
2. WHEN the ChatPanel's `resolveWebviewView` is called and Chat_History exists in Workspace_State, THE ChatPanel SHALL send all stored messages to the Webview for rendering
3. THE ChatPanel SHALL store each message in Chat_History with its role and content fields
4. WHEN the user starts a new session (no stored Session_ID), THE ChatPanel SHALL clear the existing Chat_History from Workspace_State

### Requirement 4: Webview Message State Across Visibility Changes

**User Story:** As a developer, I want the chat messages to remain visible when I switch tabs and come back to the chat panel, so that I do not see a blank panel.

#### Acceptance Criteria

1. WHEN a message is rendered in the Webview, THE Webview SHALL save the current messages array to Webview_State using `setState`
2. WHEN the Webview script initializes, THE Webview SHALL check for existing state via `getState` and render any stored messages
3. FOR ALL message arrays stored via `setState`, restoring via `getState` and rendering SHALL produce the same visible messages (round-trip property)

### Requirement 5: Server-Side Session Persistence

**User Story:** As a developer, I want my sessions to survive server restarts, so that I can resume work after the server is restarted.

#### Acceptance Criteria

1. WHEN an AgentSession is created or updated, THE Agent_Server SHALL persist the session data to the Session_Store
2. WHEN the Agent_Server starts up, THE Agent_Server SHALL load existing sessions from the Session_Store into memory
3. FOR ALL valid AgentSession objects, serializing to JSON and deserializing back SHALL produce an equivalent AgentSession (round-trip property)
4. IF the Session_Store file is corrupt or unreadable, THEN THE Agent_Server SHALL log a warning and start with an empty session dictionary
5. THE Agent_Server SHALL store the Session_Store file in the configured data directory

### Requirement 6: Session Resume on Reconnect

**User Story:** As a developer, I want the server to pick up where it left off when my extension reconnects with an existing session ID, so that I do not lose completed work.

#### Acceptance Criteria

1. WHEN the Agent_Server receives a prompt request with a Session_ID that exists in storage, THE Agent_Server SHALL reuse the existing AgentSession
2. WHEN the Agent_Server receives a status request for a Session_ID that exists in storage, THE Agent_Server SHALL return the full session state including plan, execution result, and pending changes
3. WHEN the Agent_Server receives a prompt request with a Session_ID that does not exist, THE Agent_Server SHALL create a new session with that Session_ID
