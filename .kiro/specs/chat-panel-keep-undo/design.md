# Design Document

## Overview

This design moves the Keep/Undo decision from a VS Code toast notification into the chat panel webview as inline action buttons. The change touches three layers: the DiffProvider (removes toast, exposes a callback), the ChatPanel (new message type and webview message handlers), and the webview HTML/JS (renders buttons, handles clicks, shows results).

## Architecture

### Message Flow

```
DiffProvider.showChanges()
  ├── writes files to disk (unchanged)
  ├── calls onChangesWritten callback (NEW) instead of showInformationMessage
  │
ChatPanel receives callback
  ├── posts 'showActionButtons' message to webview
  │
Webview renders Keep/Undo buttons
  ├── User clicks Keep → postMessage({ type: 'keepChanges' })
  ├── User clicks Undo → postMessage({ type: 'undoChanges' })
  │
ChatPanel.onDidReceiveMessage handler
  ├── 'keepChanges' → calls DiffProvider.acceptChanges()
  ├── 'undoChanges' → calls DiffProvider.undoChanges()
  ├── posts 'actionResult' message to webview with success/error
  │
Webview receives actionResult
  └── replaces buttons with confirmation or error message
```

### Component Changes

#### 1. DiffProvider Changes (`diffProvider.ts`)

- Add `onChangesWritten` callback property: `(summary: string, sessionId: string) => void`
- Modify `showChanges()`: after writing files to disk, invoke `onChangesWritten` callback with the summary message and session ID instead of calling `vscode.window.showInformationMessage`
- Remove the `showInformationMessage` call and the `if (choice === 'Undo')` block
- Keep `acceptChanges()` and `undoChanges()` as public methods (called by ChatPanel)

```typescript
// New callback type on DiffProvider
public onChangesWritten?: (summary: string, sessionId: string) => void;

// In showChanges(), replace the toast block with:
if (this.onChangesWritten) {
    this.onChangesWritten(message, this.sessionId);
}
```

#### 2. ChatPanel Changes (`chatPanel.ts`)

- Add new method `showActionButtons(summary: string, sessionId: string)` that posts a `showActionButtons` message to the webview
- Extend `onDidReceiveMessage` handler to process `keepChanges` and `undoChanges` message types
- Store a reference to DiffProvider (passed via constructor or setter) to call `acceptChanges()`/`undoChanges()`
- Post `actionResult` message back to webview after action completes

```typescript
// New method
public showActionButtons(summary: string, sessionId: string): void {
    this.postMessageToWebview({
        type: 'showActionButtons',
        summary,
        sessionId,
    });
}

// In resolveWebviewView, extend onDidReceiveMessage:
case 'keepChanges':
    // call diffProvider.acceptChanges(), post result
    break;
case 'undoChanges':
    // call diffProvider.undoChanges(), post result
    break;
```

#### 3. Extension Wiring Changes (`extension.ts`)

- Set `diffProvider.onChangesWritten` callback to call `chatPanel.showActionButtons()`
- Pass `diffProvider` reference to `chatPanel` (via setter method `setDiffProvider()`)

```typescript
diffProvider.onChangesWritten = (summary, sessionId) => {
    chatPanel.showActionButtons(summary, sessionId);
};
chatPanel.setDiffProvider(diffProvider);
```

#### 4. Webview HTML/JS Changes (`chatPanel.ts` → `getHtmlForWebview()`)

- Add CSS for `.action-buttons` container and button styles using VS Code theme variables
- Add handler for `showActionButtons` message type: creates a message div with summary text and Keep/Undo buttons
- Add click handlers on buttons that call `vscode.postMessage({ type: 'keepChanges' })` or `vscode.postMessage({ type: 'undoChanges' })`
- Add handler for `actionResult` message type: replaces the action buttons div with a confirmation or error message
- Track active action buttons element ID to support the single-active-set constraint

```css
.action-buttons {
    display: flex;
    gap: 8px;
    margin-top: 6px;
}
.action-buttons button {
    padding: 4px 12px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
    font-size: inherit;
}
.action-buttons .keep-btn {
    background-color: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
}
.action-buttons .keep-btn:hover {
    background-color: var(--vscode-button-hoverBackground);
}
.action-buttons .undo-btn {
    background-color: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
}
.action-buttons .undo-btn:hover {
    background-color: var(--vscode-button-secondaryHoverBackground);
}
```

```javascript
// In the message handler switch:
case 'showActionButtons': {
    // Remove any existing action buttons (single-active constraint)
    const existing = document.querySelector('.action-buttons-container');
    if (existing) {
        existing.querySelector('.action-buttons')?.remove();
        // Add a "superseded" note
    }

    const div = document.createElement('div');
    div.className = 'message agent action-buttons-container';
    div.dataset.sessionId = msg.sessionId;
    div.innerHTML = renderContent(msg.summary) +
        '<div class="action-buttons">' +
        '<button class="keep-btn" onclick="handleKeep()">Keep</button>' +
        '<button class="undo-btn" onclick="handleUndo()">Undo</button>' +
        '</div>';
    messagesEl.appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });
    break;
}
case 'actionResult': {
    const container = document.querySelector('.action-buttons-container');
    if (container) {
        const btns = container.querySelector('.action-buttons');
        if (btns) btns.remove();
        const result = document.createElement('div');
        result.className = msg.success ? 'action-result success' : 'action-result error';
        result.textContent = msg.message;
        container.appendChild(result);
    }
    break;
}
```

## Correctness Properties

### Property 1: Action buttons appear after changes are written (Req 1.1, 1.3)
- WHEN `showActionButtons` message is posted to the webview, THEN the messages container SHALL contain a div with class `action-buttons-container` that includes both a Keep and an Undo button.

### Property 2: Keep button triggers acceptChanges (Req 2.1, 2.2)
- WHEN the user clicks the Keep button, THEN `vscode.postMessage` SHALL be called with `{ type: 'keepChanges' }`, AND the ChatPanel SHALL invoke `DiffProvider.acceptChanges()`.

### Property 3: Undo button triggers undoChanges (Req 3.1, 3.2)
- WHEN the user clicks the Undo button, THEN `vscode.postMessage` SHALL be called with `{ type: 'undoChanges' }`, AND the ChatPanel SHALL invoke `DiffProvider.undoChanges()`.

### Property 4: Buttons replaced after action (Req 2.3, 3.3)
- WHEN an `actionResult` message with `success: true` is received, THEN the action buttons SHALL be removed from the DOM and replaced with a confirmation text message.

### Property 5: Toast notification removed (Req 4.1)
- WHEN `showChanges()` completes, THEN `vscode.window.showInformationMessage` SHALL NOT be called for the Keep/Undo decision.

### Property 6: Single active button set (Req 5.1, 5.2)
- WHEN a second `showActionButtons` message arrives while buttons from a previous set exist, THEN the previous buttons SHALL be removed before the new ones are rendered.

### Property 7: Error feedback preserves buttons (Req 6.1, 6.2)
- WHEN an `actionResult` message with `success: false` is received, THEN the action buttons SHALL remain visible AND an error message SHALL be displayed.

## File Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `vscode-extension/src/diffProvider.ts` | Modify | Add `onChangesWritten` callback, remove toast notification from `showChanges()` |
| `vscode-extension/src/chatPanel.ts` | Modify | Add `showActionButtons()` method, `setDiffProvider()` setter, extend `onDidReceiveMessage`, add webview CSS/JS for action buttons |
| `vscode-extension/src/extension.ts` | Modify | Wire `diffProvider.onChangesWritten` to `chatPanel.showActionButtons`, pass diffProvider to chatPanel |
| `vscode-extension/src/__tests__/chatPanel.test.ts` | Create | Tests for showActionButtons, keepChanges/undoChanges message handling |
| `vscode-extension/src/__tests__/diffProvider.test.ts` | Modify | Update tests to verify toast is removed and callback is invoked |
