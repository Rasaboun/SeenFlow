import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createServer } from "node:net";
import { resolve } from "node:path";

export interface SidecarHandle {
  url: string;
  token: string;
  stop(): Promise<void>;
}

export async function startSidecar(options: { debug?: boolean } = {}): Promise<SidecarHandle> {
  const port = await availablePort();
  const token = randomBytes(32).toString("hex");
  const url = `http://127.0.0.1:${port}`;
  const project = resolve(import.meta.dirname, "../../../vision");
  const child = spawn("uv", ["run", "--project", project, "maestro-vision-sidecar"], {
    env: {
      ...process.env,
      MAESTRO_VISION_PORT: String(port),
      MAESTRO_VISION_SESSION_TOKEN: token,
    },
    stdio: options.debug ? "inherit" : "ignore",
  });
  let spawnError: Error | undefined;
  child.once("error", (error) => {
    spawnError = error;
  });

  const stop = async () => {
    if (child.exitCode !== null) return;
    child.kill("SIGTERM");
    await new Promise<void>((done) => child.once("close", () => done()));
  };

  try {
    await waitForHealth(url, token, () => spawnError ?? (child.exitCode === null ? undefined : new Error(`Sidecar exited with code ${child.exitCode}`)));
  } catch (error) {
    await stop();
    throw error;
  }
  return { url, token, stop };
}

async function availablePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not allocate a sidecar port");
  await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return address.port;
}

async function waitForHealth(url: string, token: string, childError: () => Error | undefined) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const failure = childError();
    if (failure) throw failure;
    try {
      const response = await fetch(`${url}/v1/health`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Vision sidecar did not become healthy within 120000ms");
}
