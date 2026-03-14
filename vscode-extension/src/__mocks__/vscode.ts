// Manual mock for the 'vscode' module used in tests

const EventEmitter = jest.fn().mockImplementation(() => {
    const listeners: Function[] = [];
    return {
        fire: jest.fn((data: any) => {
            listeners.forEach((l) => l(data));
        }),
        event: jest.fn((listener: Function) => {
            listeners.push(listener);
            return { dispose: jest.fn() };
        }),
        dispose: jest.fn(),
    };
});

const Uri = {
    parse: jest.fn((str: string) => ({
        toString: () => str,
        scheme: str.split(':')[0] || '',
        path: str,
        fsPath: str,
    })),
    file: jest.fn((path: string) => ({
        toString: () => `file://${path}`,
        scheme: 'file',
        path,
        fsPath: path,
    })),
    joinPath: jest.fn((base: any, ...segments: string[]) => {
        const joined = segments.join('/');
        const full = `${base.toString()}/${joined}`;
        return {
            toString: () => full,
            scheme: base.scheme || 'file',
            path: full,
            fsPath: full,
        };
    }),
};

const createStatusBarItem = jest.fn(() => ({
    text: '',
    command: '',
    tooltip: '',
    show: jest.fn(),
    hide: jest.fn(),
    dispose: jest.fn(),
}));

const window = {
    createStatusBarItem,
    showInformationMessage: jest.fn(),
    showWarningMessage: jest.fn(),
    showErrorMessage: jest.fn(),
    showInputBox: jest.fn(),
};

const commands = {
    executeCommand: jest.fn(),
    registerCommand: jest.fn((_command: string, _callback: Function) => ({
        dispose: jest.fn(),
    })),
};

class CompletionItem {
    label: string;
    kind?: number;
    detail?: string;
    insertText?: string;
    documentation?: any;
    constructor(label: string, kind?: number) {
        this.label = label;
        this.kind = kind;
    }
}

const CompletionItemKind = {
    Snippet: 15,
    Text: 0,
    Method: 1,
    Function: 2,
    Constructor: 3,
    Field: 4,
    Variable: 5,
    Class: 6,
    Interface: 7,
    Module: 8,
    Property: 9,
    Unit: 10,
    Value: 11,
    Enum: 12,
    Keyword: 13,
    Color: 14,
};

class MarkdownString {
    value: string;
    constructor(value?: string) {
        this.value = value || '';
    }
}

const workspace = {
    registerTextDocumentContentProvider: jest.fn(() => ({
        dispose: jest.fn(),
    })),
    workspaceFolders: [
        {
            uri: {
                toString: () => 'file:///workspace',
                scheme: 'file',
                path: '/workspace',
                fsPath: '/workspace',
            },
            name: 'workspace',
            index: 0,
        },
    ],
};

const StatusBarAlignment = {
    Left: 1,
    Right: 2,
};

module.exports = {
    Uri,
    window,
    commands,
    workspace,
    StatusBarAlignment,
    EventEmitter,
    CompletionItem,
    CompletionItemKind,
    MarkdownString,
};
