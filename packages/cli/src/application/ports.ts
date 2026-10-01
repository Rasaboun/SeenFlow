export interface RunFlowOptions {
  flow: string;
  device?: string;
  debug: boolean;
  runId: string;
}

export interface TestSession {
  run(options: RunFlowOptions): Promise<number>;
  captureFinal(runId: string): Promise<void>;
  stop(): Promise<void>;
}

export interface SessionOptions {
  debug?: boolean;
  artifactsDir?: string;
}

export interface TestFlowPorts {
  validate(source: string): Promise<void>;
  compile(source: string): Promise<void>;
  startSession(options: SessionOptions): Promise<TestSession>;
  removeArtifacts(runId: string): Promise<void>;
  createRunId(): string;
  installSignalCleanup(stop: () => Promise<void>): () => void;
  log(message: string): void;
  warn(message: string): void;
}
