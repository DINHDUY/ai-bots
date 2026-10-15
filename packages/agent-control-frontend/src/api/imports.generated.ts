/* Generated from imports.schema.json; run npm run generate:wire. */

export type WorkspaceName = string;
export type Framework = string;
export type CredentialId = string;
export type Model = string;
export type ToolSelection = ImportTool[] | null;
export type LibraryId = string;
export type ToolId = string;
export type Version = string;
export type FileId = string;
export type Filename = string;
export type Content = string;
export type Name = string | null;
export type Purpose = string | null;
/**
 * @minItems 1
 * @maxItems 50
 */
export type Files = SourceFile[];
export type WorkspaceName1 = string;
/**
 * @minItems 1
 * @maxItems 50
 */
export type Files1 = SourceFile[];
export type RequestId = string;
export type PreviewDigest = string;
export type WorkspaceName2 = string;
export type FileId1 = string;
export type Filename1 = string;
export type Name1 = string;
export type Purpose1 = string;
export type Instructions = string;
export type Field = string;
export type Code = string;
export type Message = string;
export type Errors = ImportIssue[];
export type Warnings = string[];
export type Files2 = PreviewFile[];
export type Errors1 = ImportIssue[];
export type Valid = boolean;
export type ParserVersion = string;
export type PreviewDigest1 = string;
export type RequestId1 = string;
export type WorkspaceId = string;
export type WorkspaceName3 = string;
export type FileId2 = string;
export type Filename2 = string;
export type BotId = string;
export type Name2 = string;
export type SourceHash = string;
export type BodyHash = string;
export type Bots = ImportedBot[];
export type ComputerMode = "shared";
export type ComputerProvider = "docker";
export type CollaborationEnabled = true;

/**
 * Root for generating all frontend request/response types.
 */
export interface ImportContracts {
  draft: ImportDraft;
  command: ImportCommand;
  preview: ImportPreview;
  result: ImportResult;
}
export interface ImportDraft {
  workspace_name: WorkspaceName;
  defaults?: RuntimeChoice;
  files: Files;
}
export interface RuntimeChoice {
  framework?: Framework;
  credential_id?: CredentialId;
  model?: Model;
  tool_selection?: ToolSelection;
}
export interface ImportTool {
  library_id: LibraryId;
  tool_id: ToolId;
  version: Version;
  configuration?: Configuration;
}
export interface Configuration {
  [k: string]: string;
}
export interface SourceFile {
  file_id: FileId;
  filename: Filename;
  content: Content;
  overrides?: AgentOverrides;
}
export interface AgentOverrides {
  name?: Name;
  purpose?: Purpose;
  runtime?: RuntimeChoice | null;
}
export interface ImportCommand {
  workspace_name: WorkspaceName1;
  defaults?: RuntimeChoice;
  files: Files1;
  request_id: RequestId;
  preview_digest: PreviewDigest;
}
export interface ImportPreview {
  workspace_name: WorkspaceName2;
  files: Files2;
  errors?: Errors1;
  valid?: Valid;
  parser_version?: ParserVersion;
  preview_digest?: PreviewDigest1;
}
export interface PreviewFile {
  file_id: FileId1;
  filename: Filename1;
  name: Name1;
  purpose: Purpose1;
  instructions: Instructions;
  runtime: RuntimeChoice;
  errors?: Errors;
  warnings?: Warnings;
}
export interface ImportIssue {
  field: Field;
  code: Code;
  message: Message;
}
export interface ImportResult {
  request_id: RequestId1;
  workspace_id: WorkspaceId;
  workspace_name: WorkspaceName3;
  bots: Bots;
  computer_mode?: ComputerMode;
  computer_provider?: ComputerProvider;
  collaboration_enabled?: CollaborationEnabled;
}
export interface ImportedBot {
  file_id: FileId2;
  filename: Filename2;
  bot_id: BotId;
  name: Name2;
  source_hash: SourceHash;
  body_hash: BodyHash;
}
