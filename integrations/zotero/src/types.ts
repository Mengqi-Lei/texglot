export type TargetLanguage = "简体中文" | "繁體中文" | "English" | string;

export type ArxivSource = { type: "arxiv"; id: string };
export type LatexSource = { type: "latex"; path: string; filename?: string; contentBase64?: string; main?: string };
export type TranslationSource = ArxivSource | LatexSource;

export interface ZoteroLikeItem {
  id?: number;
  key?: string;
  libraryID?: number;
  deleted?: boolean;
  isRegularItem?: () => boolean;
  isNote?: () => boolean;
  isAttachment?: () => boolean;
  isFileAttachment?: () => boolean;
  attachmentContentType?: string;
  attachmentFilename?: string;
  attachmentPath?: string;
  parentItemID?: number | false;
  parentID?: number | false;
  getParentID?: () => number | false;
  getField?: (field: string) => unknown;
  getAttachments?: () => number[] | Record<string, number>;
  getBestAttachment?: () => Promise<ZoteroLikeItem | false>;
  loadDataType?: (type: string) => Promise<unknown>;
  getFilePath?: () => Promise<string | false> | string | false;
  getFilePathAsync?: () => Promise<string | false>;
  fileExists?: () => Promise<boolean>;
  getNote?: () => string;
}

export interface SourceSelection {
  source: TranslationSource;
  parent: ZoteroLikeItem;
  attachment?: ZoteroLikeItem;
  warnings: string[];
  sourceEvidence?: string;
  sourceFingerprint?: string;
  useTaskOriginal?: boolean;
}

export interface PdfSourceInfo {
  text: string;
  fingerprint?: string;
  readable?: boolean;
}

export interface BridgeHealth {
  ok: boolean;
  name: string;
  version?: string;
  integrationApi?: string;
  dataDir?: string;
  capabilities: {
    arxivLatex: boolean;
    latexUpload: boolean;
    pdfReflow: boolean;
    translatedSource: boolean;
    readerDeepLink: boolean;
    libraryReuse?: boolean;
    arxivResolution?: boolean;
    originalPdf?: boolean;
  };
}

export type TaskStatus =
  | "queued"
  | "downloading"
  | "preparing"
  | "checking_layout"
  | "translating"
  | "compiling"
  | "completed"
  | "completed_with_warnings"
  | "needs_retry"
  | "needs_selection"
  | "cancelled"
  | "failed"
  | string;

export interface TaskSnapshot {
  id: string;
  status: TaskStatus;
  progress?: { done?: number; total?: number; percent?: number };
  message?: string;
  quality?: string;
  reuse?: "library" | "active" | "replay" | null;
  source?: { type?: string; id?: string };
  error?: { code?: string; message?: string } | string | null;
  artifacts?: { translatedPdf?: boolean; translatedSource?: boolean };
  [key: string]: unknown;
}

export interface BridgeFetchOptions {
  fetch?: typeof globalThis.fetch;
  baseUrl?: string;
  timeoutMs?: number;
}

export interface JobOptions {
  language?: TargetLanguage;
  contextGuidance?: boolean;
  importTranslatedSource?: boolean;
  open?: "comparison" | "translated" | "none";
  itemKey?: string;
  libraryId?: number;
  idempotencyKey?: string;
  reuseExisting?: boolean;
}

export interface ZoteroRuntime {
  document?: Document;
  iconURI?: string;
  isMac?: boolean;
  /** Release listeners and split-reader state when the add-on is reloaded. */
  dispose?: () => void;
  /** Register a native Zotero 8/9 library-item menu when the host exposes it. */
  registerContextMenu?: (handler: (items: ZoteroLikeItem[], options?: JobOptions) => void) => (() => void) | undefined;
  getSelectedItems?: () => ZoteroLikeItem[];
  resolveItem?: (id: number) => ZoteroLikeItem | undefined;
  resolveItemAsync?: (id: number) => Promise<ZoteroLikeItem | undefined>;
  readFile?: (path: string) => Promise<Uint8Array>;
  readPdfInfo?: (item: ZoteroLikeItem) => Promise<PdfSourceInfo>;
  hashBytes?: (bytes: Uint8Array) => Promise<string>;
  chooseAttachment?: (items: Array<{ item: ZoteroLikeItem; version?: string }>) => Promise<ZoteroLikeItem | undefined>;
  confirmOfficialSource?: (id: string, canChooseAttachment: boolean) => Promise<"official" | "choose" | "cancel">;
  notify?: (message: string, level?: "info" | "error") => void;
  setTranslationActivity?: (parent: ZoteroLikeItem, requestKey: string, activity: TranslationActivity | null) => void;
  openSettings?: () => void;
  openReader?: (taskId: string, mode?: "comparison" | "translated", baseUrl?: string) => void;
  importAttachment?: (bytes: Uint8Array, options: {
    parent: ZoteroLikeItem;
    title: string;
    note: string;
    extension: "pdf" | "zip";
  }) => Promise<unknown>;
  findAttachment?: (parent: ZoteroLikeItem, note: string) => Promise<unknown> | unknown;
  findPdfAttachment?: (parent: ZoteroLikeItem) => ZoteroLikeItem | undefined;
  findTranslatedPdf?: (parent: ZoteroLikeItem, arxivId?: string) => ZoteroLikeItem | undefined;
  openSplitReader?: (original: ZoteroLikeItem, translated: ZoteroLikeItem) => Promise<void>;
}

export interface TranslationActivity {
  state: "processing" | "review";
  message?: string;
}
