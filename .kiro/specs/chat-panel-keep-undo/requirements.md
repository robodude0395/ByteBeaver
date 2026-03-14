# Requirements Document

## Introduction

Move the Keep/Undo user decision from a VS Code toast notification (`showInformationMessage`) into the chat panel webview as inline action buttons. When the agent proposes file changes, the DiffProvider writes files to disk (unchanged behavior) and the chat panel displays Keep and Undo buttons inline, similar to GitHub Copilot's inline action pattern. This replaces the modal toast notification with a non-intrusive, contextual UI element embedded in the conversation flow.

## Glossary

- **Chat_Panel**: The VS Code webview sidebar (`ChatPanel` class) that displays the conversation between the user and the agent.
- **DiffProvider**: The class responsible for writing proposed file changes to disk, tracking original content for undo, and coordinating Keep/Undo actions.
- **Webview**: The HTML/CSS/JS content rendered inside the Chat_Panel using the VS Code webview API.
- **Action_Buttons**: Inline Keep and Undo buttons rendered within a chat message in the Webview.
- **Agent_Client**: The HTTP client that communicates with the agent server, including notifying the server when changes are accepted.
- **Pending_Changes**: The set of file changes proposed by the agent that have been written to disk but not yet confirmed or reverted by the user.

## Requirements

### Requirement 1: Display Inline Action Buttons for Pending Changes

**User Story:** As a developer, I want to see Keep and Undo buttons inline in the chat panel when the agent proposes file changes, so that I can make my decision without context-switching to a toast notification.

#### Acceptance Criteria

1. WHEN the DiffProvider finishes writing Pending_Changes to disk, THE Chat_Panel SHALL display a message containing the change summary and inline Action_Buttons labeled "Keep" and "Undo".
2. THE Action_Buttons SHALL be styled consistently with VS Code's button theming variables (button background, foreground, and hover colors).
3. THE Chat_Panel SHALL display the Action_Buttons within the conversation flow, positioned after the pending changes summary message.
4. THE Action_Buttons SHALL remain visible and interactive until the user clicks one of them.

### Requirement 2: Keep Action via Chat Panel

**User Story:** As a developer, I want to click the Keep button in the chat panel to accept the proposed changes, so that the agent server is notified and the changes are finalized.

#### Acceptance Criteria

1. WHEN the user clicks the "Keep" Action_Button, THE Chat_Panel SHALL send a message to the extension host indicating the user chose to keep changes.
2. WHEN the extension host receives a keep-changes message, THE DiffProvider SHALL execute the same accept logic as the existing `acceptChanges()` method (notify the Agent_Client and clear state).
3. WHEN the keep action completes successfully, THE Chat_Panel SHALL replace the Action_Buttons with a confirmation message indicating changes were kept.

### Requirement 3: Undo Action via Chat Panel

**User Story:** As a developer, I want to click the Undo button in the chat panel to revert the proposed changes, so that all modified files are restored to their original content.

#### Acceptance Criteria

1. WHEN the user clicks the "Undo" Action_Button, THE Chat_Panel SHALL send a message to the extension host indicating the user chose to undo changes.
2. WHEN the extension host receives an undo-changes message, THE DiffProvider SHALL execute the same revert logic as the existing `undoChanges()` method (restore original file content and clear state).
3. WHEN the undo action completes successfully, THE Chat_Panel SHALL replace the Action_Buttons with a confirmation message indicating changes were reverted.

### Requirement 4: Remove Toast Notification

**User Story:** As a developer, I want the VS Code toast notification for Keep/Undo to be removed, so that there is a single, consistent place to make the decision.

#### Acceptance Criteria

1. WHEN the DiffProvider writes Pending_Changes to disk, THE DiffProvider SHALL NOT display a `showInformationMessage` toast notification for the Keep/Undo decision.
2. THE DiffProvider SHALL delegate the user decision to the Chat_Panel by invoking a callback or event instead of awaiting the toast response.

### Requirement 5: Single Active Action Buttons Constraint

**User Story:** As a developer, I want only one set of Keep/Undo buttons to be active at a time, so that I cannot accidentally act on stale change sets.

#### Acceptance Criteria

1. WHEN new Pending_Changes arrive while Action_Buttons from a previous change set are still displayed, THE Chat_Panel SHALL disable or remove the previous Action_Buttons before displaying new ones.
2. THE Chat_Panel SHALL associate each set of Action_Buttons with the corresponding session ID and change set to prevent mismatched actions.

### Requirement 6: Error Handling for Keep/Undo Actions

**User Story:** As a developer, I want to see clear feedback if the Keep or Undo action fails, so that I know the state of my files.

#### Acceptance Criteria

1. IF the keep action fails to notify the Agent_Client, THEN THE Chat_Panel SHALL display an error message below the Action_Buttons and keep the buttons visible for retry.
2. IF the undo action fails to restore one or more files, THEN THE Chat_Panel SHALL display an error message listing the files that could not be reverted.
