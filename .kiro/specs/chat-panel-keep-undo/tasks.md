# Tasks

## Task 1: Add onChangesWritten callback to DiffProvider and remove toast notification
- [ ] 1.1 Add `onChangesWritten` callback property to `DiffProvider` class in `vscode-extension/src/diffProvider.ts`
- [ ] 1.2 Modify `showChanges()` to invoke `onChangesWritten` callback with summary message and session ID instead of calling `vscode.window.showInformationMessage`
- [ ] 1.3 Remove the `showInformationMessage` call and the Keep/Undo choice handling block from `showChanges()`
- [ ] 1.4 Update existing tests in `vscode-extension/src/__tests__/diffProvider.test.ts` to verify the callback is invoked and toast is not called

## Task 2: Add action button support to ChatPanel
- [ ] 2.1 Add `setDiffProvider(diffProvider: DiffProvider)` setter method to `ChatPanel` in `vscode-extension/src/chatPanel.ts`
- [ ] 2.2 Add `showActionButtons(summary: string, sessionId: string)` method that posts a `showActionButtons` message to the webview
- [ ] 2.3 Extend `onDidReceiveMessage` handler in `resolveWebviewView` to handle `keepChanges` message type — call `diffProvider.acceptChanges()` and post `actionResult` back to webview
- [ ] 2.4 Extend `onDidReceiveMessage` handler to handle `undoChanges` message type — call `diffProvider.undoChanges()` and post `actionResult` back to webview
- [ ] 2.5 Add error handling: wrap acceptChanges/undoChanges in try/catch, post `actionResult` with `success: false` and error message on failure

## Task 3: Add webview HTML/CSS/JS for inline action buttons
- [ ] 3.1 Add CSS styles for `.action-buttons-container`, `.action-buttons`, `.keep-btn`, `.undo-btn`, and `.action-result` classes in `getHtmlForWebview()` using VS Code theme variables
- [ ] 3.2 Add `showActionButtons` message handler in the webview `<script>` that renders the summary text with Keep and Undo buttons
- [ ] 3.3 Add `handleKeep()` and `handleUndo()` functions in the webview script that call `vscode.postMessage` with the appropriate type
- [ ] 3.4 Add `actionResult` message handler in the webview script that replaces buttons with confirmation text on success, or shows error message while preserving buttons on failure
- [ ] 3.5 Implement single-active-set constraint: when `showActionButtons` is received, remove any existing action buttons from a previous change set

## Task 4: Wire up DiffProvider and ChatPanel in extension.ts
- [ ] 4.1 In `extension.ts`, call `chatPanel.setDiffProvider(diffProvider)` after both are created
- [ ] 4.2 Set `diffProvider.onChangesWritten` callback to invoke `chatPanel.showActionButtons(summary, sessionId)`

## Task 5: Write tests for ChatPanel action button handling
- [ ] 5.1 Create `vscode-extension/src/__tests__/chatPanel.test.ts` with tests for `showActionButtons` posting the correct webview message
- [ ] 5.2 Add tests for `keepChanges` message handler calling `diffProvider.acceptChanges()` and posting success result
- [ ] 5.3 Add tests for `undoChanges` message handler calling `diffProvider.undoChanges()` and posting success result
- [ ] 5.4 Add tests for error scenarios: acceptChanges/undoChanges throwing errors results in `actionResult` with `success: false`
