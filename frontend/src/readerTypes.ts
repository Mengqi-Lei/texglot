export type DocumentSide = "original" | "translated";
export type ReaderMode = DocumentSide | "split";
export type AnnotationKind = "highlight" | "underline" | "note";
export type ReaderTool = "select" | AnnotationKind;
export const colors = {
  yellow: "#ffd75e",
  green: "#80d8a4",
  blue: "#78baff",
  pink: "#f59db5",
  purple: "#c3a0f0",
} as const;
export type AnnotationColor = keyof typeof colors;
export const colorNames = {
  yellow: "黄色",
  green: "绿色",
  blue: "蓝色",
  pink: "粉色",
  purple: "紫色",
};
export type Rect = { x: number; y: number; width: number; height: number };
export type Anchor = { page: number; rects: Rect[] };
export type AnnotationInput = {
  id: string;
  document: DocumentSide;
  document_version: string;
  kind: AnnotationKind;
  color: AnnotationColor;
  anchors: Anchor[];
  quote: string;
  comment: string;
};
export type Annotation = AnnotationInput & {
  revision: number;
  deleted: boolean;
  created_at: number;
  updated_at: number;
};
export type PagePosition = {
  page: number;
  fraction: number;
  viewport?: number;
};
export type Alignment = {
  version: number;
  kind: "landmarks" | "pages";
  documents: Record<DocumentSide, string>;
  heights: Record<DocumentSide, number[]>;
  pairs: { id: string; original: PagePosition; translated: PagePosition }[];
  regions?: {
    id: string;
    original: { page: number; start: number; end: number };
    translated: { page: number; start: number; end: number };
  }[];
};
export type DocumentInfo = { version: string; pages: number };
export type ReadingState = {
  positions: Partial<
    Record<DocumentSide, PagePosition & { document_version: string }>
  >;
  active: DocumentSide;
  mode: ReaderMode;
  zoom: number;
  sync: boolean;
};
export type ReaderData = {
  documents: Partial<Record<DocumentSide, DocumentInfo>>;
  annotations: Annotation[];
  alignment?: Alignment | null;
  reading: ReadingState | null;
};
export type SelectionDraft = {
  document: DocumentSide;
  document_version: string;
  anchors: Anchor[];
  quote: string;
  x: number;
  y: number;
};
