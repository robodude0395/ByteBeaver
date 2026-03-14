# Requirements Document

## Introduction

The VSCode extension currently delegates file writing to the agent server via `POST /agent/apply_changes`. This fails when the extension runs on a different machine (e.g., a Mac laptop) than the agent server (e.g., a remote Linux desktop with GPU). This feature moves file writing to the client side, using the VSCode workspace filesystem API (`vscode.workspace.fs`) so that accepted changes are written directly to the local workspace. The server is optionally notified afterward for session state tracking.

## Glossary

- **Extension**: The VSCode extension that provides the user interface for interacting with the agent
- **Agent_Server**: The remote FastAPI server that runs LLM inference and produces code changes
- **DiffProvider**: The Extension component that manages diff previews and the accept/reject workflow for proposed changes
- **AgentClient**: The Extension component that communicates with the Agent_Server REST API
- **FileChangeInfo**: A data structure containing change_id, file_path, change_type, and diff fields describing a single proposed file change
- **Workspace_Root**: The root directory of the currently open VSCode workspace folder
- **Workspace_FS**: The VSCode workspace filesystem API (`vscode.workspace.fs`) used for local file operations
- **Pending_Changes**: The list of FileChangeInfo objects returned by the Agent_Server that have not yet been applied or rejected

## Requirements

### Requirement 1: Local File Writing on Accept

**User Story:** As a developer, I want accepted changes to be written to my local filesystem, so that the extension works correctly when the Agent_Server runs on a remote machine.

#### Acceptance Criteria

1. WHEN the user accepts Pending_Changes, THE DiffProvider SHALL write each change's content to the local filesystem using Workspace_FS instead of calling the Agent_Server's apply_changes endpoint
2. WHEN writing a file change, THE DiffProvider SHALL resolve the file path relative to the Workspace_Root
3. WHEN a FileChangeInfo has a change_type of "create", THE DiffProvider SHALL create the file at the resolved path with the content from the diff field
4. WHEN a FileChangeInfo has a change_type of "modify", THE DiffProvider SHALL overwrite the file at the resolved path with the content from the diff field
5. WHEN a FileChangeInfo has a change_type of "delete", THE DiffProvider SHALL delete the file at the resolved path

### Requirement 2: Parent Directory Creation

**User Story:** As a developer, I want parent directories to be created automatically when a new file is written, so that file creation works for deeply nested paths.

#### Acceptance Criteria

1. WHEN writing a file whose parent directory does not exist, THE DiffProvider SHALL create all necessary parent directories before writing the file
2. WHEN creating parent directories, THE DiffProvider SHALL use Workspace_FS to ensure the operation is local

### Requirement 3: Server-Side State Notification

**User Story:** As a developer, I want the Agent_Server to be notified after changes are applied locally, so that the server's session state remains accurate.

#### Acceptance Criteria

1. WHEN changes are successfully written locally, THE DiffProvider SHALL send a notification to the Agent_Server with the list of applied change IDs
2. IF the server notification fails, THEN THE DiffProvider SHALL log the failure and continue without blocking the user, since the local write already succeeded
3. THE DiffProvider SHALL treat the local file write as the primary success criterion, not the server notification

### Requirement 4: Error Handling for Local Writes

**User Story:** As a developer, I want clear error feedback when a local file write fails, so that I can diagnose and resolve issues.

#### Acceptance Criteria

1. IF a local file write fails for a specific change, THEN THE DiffProvider SHALL report the failure to the user with the file path and error reason
2. IF one or more file writes fail, THEN THE DiffProvider SHALL continue writing the remaining changes rather than aborting the entire batch
3. WHEN all writes complete, THE DiffProvider SHALL display a summary indicating the count of successfully applied changes and the count of failed changes
4. IF all file writes fail, THEN THE DiffProvider SHALL display an error message to the user

### Requirement 5: Workspace Folder Validation

**User Story:** As a developer, I want the extension to validate that a workspace folder is open before attempting to write files, so that writes do not go to an unexpected location.

#### Acceptance Criteria

1. WHEN the user accepts changes and no workspace folder is open, THE DiffProvider SHALL display an error message and abort the operation
2. THE DiffProvider SHALL resolve all file paths against the first open workspace folder's URI

### Requirement 6: Content Extraction from FileChangeInfo

**User Story:** As a developer, I want the extension to correctly extract the new file content from the FileChangeInfo structure, so that the written files contain the correct content.

#### Acceptance Criteria

1. THE Extension SHALL extract the full new file content from the diff field of each FileChangeInfo object
2. WHEN the diff field contains the new file content, THE DiffProvider SHALL use that content as-is for writing to the local filesystem
3. FOR ALL valid FileChangeInfo objects, writing the extracted content and then reading the file back SHALL produce content identical to the diff field (round-trip property)

### Requirement 7: Diff Preview Workflow Preservation

**User Story:** As a developer, I want the existing diff preview and accept/reject workflow to remain unchanged, so that I can still review changes before accepting them.

#### Acceptance Criteria

1. THE DiffProvider SHALL continue to show diff previews using the ProposedContentProvider before the user accepts or rejects changes
2. THE DiffProvider SHALL continue to display Accept and Reject status bar buttons when Pending_Changes are available
3. WHEN the user rejects changes, THE DiffProvider SHALL clear the Pending_Changes and hide the status bar buttons without writing any files
4. WHEN the user accepts changes, THE DiffProvider SHALL clear the Pending_Changes and hide the status bar buttons after writing files locally
