/**
 * R.0 — Replay Control Proof of Concept (isolated spike).
 *
 * Proves: real .rofl → League install → launch → Replay API → pause/resume/seek.
 * Does NOT modify H.1–H.9 production code. Disposable experiment only.
 *
 * Usage:
 *   node probe.mjs
 *   node probe.mjs --rofl "C:\\path\\to\\file.rofl"
 */

import { spawn, execFile } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import https from "node:https";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = __dirname;
const SESSION_PATH = path.join(OUT_DIR, "session.jsonl");
const REPORT_PATH = path.join(OUT_DIR, "probe_report.json");
const RIOT_CA_PATH = path.join(OUT_DIR, "riotgames.pem");

const DEFAULT_ROFL = path.join(
  os.homedir(),
  "OneDrive",
  "Documents",
  "League of Legends",
  "Replays",
  "NA1-5617764200.rofl",
);

const REPLAY_HOST = "127.0.0.1";
const REPLAY_PORT = 2999;
const REPLAY_BASE = `https://${REPLAY_HOST}:${REPLAY_PORT}`;

const SEEK_TOLERANCE_S = 2.0;
const PAUSE_DRIFT_MAX_S = 0.75;
const ADVANCE_MIN_S = 1.5;
const API_WAIT_MS = 180_000;
const API_POLL_MS = 2_000;

/** @typedef {"pending"|"pass"|"fail"|"skip"|"info"} CheckStatus */

/** @type {object[]} */
const session = [];
/** @type {Record<string, any>} */
const checks = {};
/** @type {string[]} */
const failures = [];

function nowIso() {
  return new Date().toISOString();
}

function argValue(flag) {
  const idx = process.argv.indexOf(flag);
  if (idx >= 0 && process.argv[idx + 1]) return process.argv[idx + 1];
  return null;
}

async function logEvent(kind, message, data = undefined) {
  const entry = {
    ts: nowIso(),
    kind,
    message,
    ...(data !== undefined ? { data } : {}),
  };
  session.push(entry);
  const line = JSON.stringify(entry);
  await fsp.appendFile(SESSION_PATH, line + "\n", "utf8");
  const prefix = kind === "error" ? "!" : kind === "check" ? "*" : "-";
  console.log(`${prefix} [${kind}] ${message}`);
  if (data !== undefined) {
    const preview = JSON.stringify(data);
    if (preview.length < 500) console.log(`    ${preview}`);
  }
}

function recordCheck(id, status, detail, evidence = undefined) {
  checks[id] = {
    id,
    status,
    detail,
    ...(evidence !== undefined ? { evidence } : {}),
    ts: nowIso(),
  };
  if (status === "fail") failures.push(`${id}: ${detail}`);
}

function createHttpsAgent() {
  const ca = fs.readFileSync(RIOT_CA_PATH, "utf8");
  // Verify the League client certificate against Riot's published CA.
  // Hostname check is disabled because the cert is not issued for 127.0.0.1;
  // this is NOT verify=false / insecure TLS bypass.
  return new https.Agent({
    ca,
    checkServerIdentity: () => undefined,
    keepAlive: false,
  });
}

/**
 * @param {string} method
 * @param {string} urlPath
 * @param {object|null} body
 * @param {number} timeoutMs
 */
function requestJson(method, urlPath, body = null, timeoutMs = 8_000) {
  const agent = createHttpsAgent();
  const url = new URL(urlPath, REPLAY_BASE);
  const payload = body === null ? null : JSON.stringify(body);

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method,
        agent,
        headers: {
          Accept: "application/json",
          ...(payload
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(payload),
              }
            : {}),
        },
        timeout: timeoutMs,
      },
      (res) => {
        /** @type {Buffer[]} */
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const raw = Buffer.concat(chunks).toString("utf8");
          let json = null;
          if (raw.length > 0) {
            try {
              json = JSON.parse(raw);
            } catch (err) {
              resolve({
                ok: false,
                status: res.statusCode ?? 0,
                headers: res.headers,
                raw,
                json: null,
                parseError: String(err),
              });
              return;
            }
          }
          resolve({
            ok: (res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 300,
            status: res.statusCode ?? 0,
            headers: res.headers,
            raw,
            json,
            parseError: null,
          });
        });
      },
    );
    req.on("timeout", () => {
      req.destroy(new Error(`timeout after ${timeoutMs}ms`));
    });
    req.on("error", (err) => reject(err));
    if (payload) req.write(payload);
    req.end();
  });
}

async function tryRequest(method, urlPath, body = null, timeoutMs = 8_000) {
  try {
    return await requestJson(method, urlPath, body, timeoutMs);
  } catch (err) {
    return {
      ok: false,
      status: 0,
      headers: {},
      raw: "",
      json: null,
      parseError: null,
      error: String(err && err.message ? err.message : err),
    };
  }
}

async function resetOutputs() {
  await fsp.writeFile(SESSION_PATH, "", "utf8");
  if (fs.existsSync(REPORT_PATH)) await fsp.unlink(REPORT_PATH);
}

function parseRoflHeader(buf) {
  const magic = buf.subarray(0, 4).toString("ascii");
  const asText = buf.toString("latin1");
  const versionMatch = asText.match(/(\d+\.\d+\.\d+\.\d+)/);
  return {
    magic,
    looksLikeRofl: magic === "RIOT" || magic === "ROFL",
    embeddedVersion: versionMatch ? versionMatch[1] : null,
    sizeBytes: buf.length,
  };
}

async function inspectRofl(roflPath) {
  await logEvent("step", "Validate .rofl exists and is readable", { roflPath });
  const st = await fsp.stat(roflPath);
  if (!st.isFile()) throw new Error(`Not a file: ${roflPath}`);
  if (st.size < 64) throw new Error(`.rofl too small (${st.size} bytes)`);
  const fd = await fsp.open(roflPath, "r");
  try {
    const buf = Buffer.alloc(512);
    const { bytesRead } = await fd.read(buf, 0, 512, 0);
    const header = parseRoflHeader(buf.subarray(0, bytesRead));
    header.sizeBytes = st.size;
    header.mtime = st.mtime.toISOString();
    header.basename = path.basename(roflPath);
    const gameIdFromName = path.basename(roflPath).match(/NA1-(\d+)/i);
    header.gameIdHint = gameIdFromName ? gameIdFromName[1] : null;
    if (!header.looksLikeRofl) {
      recordCheck(
        "rofl_readable",
        "fail",
        `Unexpected magic ${JSON.stringify(header.magic)}; expected RIOT/ROFL`,
        header,
      );
      throw new Error("ROFL magic mismatch");
    }
    recordCheck("rofl_readable", "pass", "ROFL present and readable", header);
    await logEvent("check", "rofl_readable PASS", header);
    return header;
  } finally {
    await fd.close();
  }
}

function candidateInstallRoots() {
  const roots = [
    "C:\\Riot Games\\League of Legends",
    "D:\\Riot Games\\League of Legends",
    "E:\\Riot Games\\League of Legends",
    path.join(process.env["ProgramFiles"] || "C:\\Program Files", "Riot Games", "League of Legends"),
    path.join(process.env["ProgramFiles(x86)"] || "C:\\Program Files (x86)", "Riot Games", "League of Legends"),
  ];
  return [...new Set(roots)];
}

async function validateInstall(root) {
  const gameExe = path.join(root, "Game", "League of Legends.exe");
  const clientExe = path.join(root, "LeagueClient.exe");
  const gameCfg = path.join(root, "Config", "game.cfg");
  const codeMeta = path.join(root, "Game", "code-metadata.json");
  const missing = [];
  for (const p of [gameExe, clientExe, gameCfg]) {
    if (!fs.existsSync(p)) missing.push(p);
  }
  if (missing.length) return null;

  let clientVersion = null;
  if (fs.existsSync(codeMeta)) {
    try {
      clientVersion = JSON.parse(await fsp.readFile(codeMeta, "utf8")).version ?? null;
    } catch {
      clientVersion = null;
    }
  }

  let cfgVersion = null;
  const cfgText = await fsp.readFile(gameCfg, "utf8");
  const m = cfgText.match(/CfgVersion\s*=\s*([^\r\n]+)/i);
  if (m) cfgVersion = m[1].trim();

  return {
    root,
    gameExe,
    clientExe,
    gameCfg,
    clientVersion,
    cfgVersion,
    localeHint: "en_GB",
    regionHint: "NA",
  };
}

async function discoverLeagueInstall() {
  await logEvent("step", "Locate and validate League installation");
  for (const root of candidateInstallRoots()) {
    const info = await validateInstall(root);
    if (info) {
      recordCheck("league_install", "pass", `Validated install at ${root}`, info);
      await logEvent("check", "league_install PASS", info);
      return info;
    }
  }
  recordCheck("league_install", "fail", "No valid League install found in candidate roots", {
    candidates: candidateInstallRoots(),
  });
  throw new Error("League installation not found");
}

async function ensureReplayApiEnabled(install) {
  await logEvent("step", "Ensure EnableReplayApi=1 in game.cfg");
  const original = await fsp.readFile(install.gameCfg, "utf8");
  const hasKey = /EnableReplayApi\s*=/i.test(original);
  const enabled = /EnableReplayApi\s*=\s*1\b/i.test(original);
  if (enabled) {
    recordCheck("enable_replay_api", "pass", "EnableReplayApi already set to 1", {
      path: install.gameCfg,
    });
    await logEvent("check", "enable_replay_api already enabled");
    return { changed: false, previous: original };
  }

  let next;
  if (hasKey) {
    next = original.replace(/EnableReplayApi\s*=\s*[^\r\n]*/i, "EnableReplayApi=1");
  } else if (/\[General\]/i.test(original)) {
    next = original.replace(/\[General\]/i, "[General]\r\nEnableReplayApi=1");
  } else {
    next = `[General]\r\nEnableReplayApi=1\r\n` + original;
  }

  const backupPath = install.gameCfg + `.r0.bak.${Date.now()}`;
  await fsp.writeFile(backupPath, original, "utf8");
  await fsp.writeFile(install.gameCfg, next, "utf8");
  const verify = await fsp.readFile(install.gameCfg, "utf8");
  if (!/EnableReplayApi\s*=\s*1\b/i.test(verify)) {
    recordCheck("enable_replay_api", "fail", "Failed to write EnableReplayApi=1", {
      path: install.gameCfg,
    });
    throw new Error("Could not enable Replay API in game.cfg");
  }
  recordCheck("enable_replay_api", "pass", "Wrote EnableReplayApi=1 under [General]", {
    path: install.gameCfg,
    backupPath,
  });
  await logEvent("check", "enable_replay_api PASS", { backupPath });
  return { changed: true, backupPath, previous: original };
}

async function launchViaGameExe(install, roflPath) {
  const args = [
    roflPath,
    `-GameBaseDir=${install.root}`,
    "-Region=NA",
    "-PlatformID=NA1",
    "-Locale=en_US",
    "-SkipBuild",
    "-EnableCrashpad=true",
  ];
  await logEvent("step", "Launch replay via League of Legends.exe", {
    exe: install.gameExe,
    cwd: path.dirname(install.gameExe),
    args,
  });

  const child = spawn(install.gameExe, args, {
    cwd: path.dirname(install.gameExe),
    detached: true,
    stdio: "ignore",
    windowsHide: false,
  });
  child.unref();
  return {
    method: "game_exe_args",
    pid: child.pid ?? null,
    exe: install.gameExe,
    args,
  };
}

async function launchViaShellOpen(roflPath) {
  await logEvent("step", "Fallback launch via ShellExecute (start)");
  await new Promise((resolve, reject) => {
    execFile(
      "cmd.exe",
      ["/c", "start", "", roflPath],
      { windowsHide: true },
      (err) => (err ? reject(err) : resolve()),
    );
  });
  return { method: "shell_start", roflPath };
}

async function waitForProcess(nameContains, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const list = await listProcesses();
    const hit = list.find((p) => p.name.toLowerCase().includes(nameContains.toLowerCase()));
    if (hit) return hit;
    await delay(1_000);
  }
  return null;
}

async function listProcesses() {
  // PowerShell for reliable process listing on Windows.
  const ps = `
Get-Process | Select-Object Id,ProcessName | ConvertTo-Json -Compress
`;
  const raw = await new Promise((resolve, reject) => {
    execFile(
      "powershell.exe",
      ["-NoProfile", "-Command", ps],
      { windowsHide: true, maxBuffer: 20 * 1024 * 1024 },
      (err, stdout) => (err ? reject(err) : resolve(stdout.toString())),
    );
  });
  try {
    const parsed = JSON.parse(raw);
    const arr = Array.isArray(parsed) ? parsed : [parsed];
    return arr.map((p) => ({ pid: p.Id, name: p.ProcessName }));
  } catch {
    return [];
  }
}

async function waitForReplayApi() {
  await logEvent("step", "Poll Replay API until available", {
    base: REPLAY_BASE,
    timeoutMs: API_WAIT_MS,
  });
  const deadline = Date.now() + API_WAIT_MS;
  /** @type {any} */
  let last = null;
  while (Date.now() < deadline) {
    last = await tryRequest("GET", "/replay/playback");
    if (last.ok && last.json && typeof last.json.time === "number") {
      recordCheck("replay_api_available", "pass", "GET /replay/playback succeeded", last.json);
      await logEvent("check", "replay_api_available PASS", last.json);
      return last.json;
    }
    await logEvent("info", "Replay API not ready yet", {
      status: last.status,
      error: last.error ?? null,
      parseError: last.parseError,
    });
    await delay(API_POLL_MS);
  }
  recordCheck("replay_api_available", "fail", "Replay API did not become available in time", last);
  throw new Error("Replay API unavailable");
}

async function inventoryCapabilities() {
  await logEvent("step", "Inspect OpenAPI/Swagger and probe /replay/* + /liveclientdata/*");
  const swaggerV2 = await tryRequest("GET", "/swagger/v2/swagger.json", null, 15_000);
  const openapiV3 = await tryRequest("GET", "/swagger/v3/openapi.json", null, 15_000);

  /** @type {string[]} */
  let documentedPaths = [];
  for (const spec of [openapiV3, swaggerV2]) {
    if (spec.ok && spec.json && spec.json.paths) {
      documentedPaths = Object.keys(spec.json.paths).sort();
      break;
    }
  }

  const replayCandidates = [
    "/replay/game",
    "/replay/playback",
    "/replay/render",
    "/replay/recording",
    "/replay/sequence",
    "/replay/particles",
  ];
  const liveCandidates = [
    "/liveclientdata/allgamedata",
    "/liveclientdata/gamestats",
    "/liveclientdata/eventdata",
    "/liveclientdata/playerlist",
    "/liveclientdata/activeplayer",
    "/liveclientdata/activeplayername",
  ];

  function summarizeKeys(json) {
    if (Array.isArray(json)) {
      return { keyCount: json.length, sampleKeys: ["<array>"], truncated: false };
    }
    if (json && typeof json === "object") {
      const keys = Object.keys(json).sort();
      const max = 40;
      return {
        keyCount: keys.length,
        sampleKeys: keys.slice(0, max),
        truncated: keys.length > max,
      };
    }
    return { keyCount: 0, sampleKeys: null, truncated: false };
  }

  /** @type {Record<string, any>} */
  const replayObserved = {};
  for (const p of replayCandidates) {
    const res = await tryRequest("GET", p);
    const keys = summarizeKeys(res.json);
    replayObserved[p] = {
      reachable: !res.error,
      httpStatus: res.status,
      ok: res.ok,
      ...keys,
      error: res.error ?? res.parseError,
    };
  }

  /** @type {Record<string, any>} */
  const liveObserved = {};
  for (const p of liveCandidates) {
    const res = await tryRequest("GET", p);
    const keys = summarizeKeys(res.json);
    liveObserved[p] = {
      reachable: !res.error,
      httpStatus: res.status,
      ok: res.ok,
      ...keys,
      error: res.error ?? res.parseError,
    };
  }

  const anyLive = Object.values(liveObserved).some((v) => v.ok);
  recordCheck(
    "replay_capabilities",
    "pass",
    `Documented paths=${documentedPaths.length}; probed replay endpoints`,
    { documentedPaths, replayObserved },
  );
  recordCheck(
    "liveclientdata_during_replay",
    anyLive ? "pass" : "info",
    anyLive
      ? "At least one /liveclientdata/* endpoint responded OK during replay"
      : "No /liveclientdata/* endpoint OK during replay (non-fatal for R.0)",
    { liveObserved },
  );
  await logEvent("check", "capabilities inventoried", {
    documentedPathCount: documentedPaths.length,
    liveAvailable: anyLive,
  });

  return {
    swaggerV2Available: swaggerV2.ok,
    openapiV3Available: openapiV3.ok,
    documentedPaths,
    openapiTitle: openapiV3.json?.info?.title ?? swaggerV2.json?.info?.title ?? null,
    openapiVersion: openapiV3.json?.info?.version ?? swaggerV2.json?.info?.version ?? null,
    replayObserved,
    liveObserved,
    liveClientDataAvailable: anyLive,
    // Keep full specs out of the report if huge; store path lists + small excerpts.
    openapiPathCount: documentedPaths.length,
  };
}

async function getPlayback() {
  const res = await tryRequest("GET", "/replay/playback");
  if (!res.ok || !res.json || typeof res.json.time !== "number") {
    throw new Error(`GET /replay/playback failed: status=${res.status} error=${res.error}`);
  }
  return res.json;
}

async function postPlayback(body) {
  const res = await tryRequest("POST", "/replay/playback", body);
  if (!res.ok) {
    throw new Error(
      `POST /replay/playback failed: status=${res.status} error=${res.error ?? res.raw}`,
    );
  }
  return res.json ?? (await getPlayback());
}

async function waitUntilNotSeeking(timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const pb = await getPlayback();
    if (!pb.seeking) return pb;
    await delay(250);
  }
  return getPlayback();
}

async function proveTimeAdvances() {
  await logEvent("step", "Ensure playback is unpaused and time advances");
  await postPlayback({ paused: false, speed: 1 });
  await delay(500);
  const t0 = await getPlayback();
  await delay(3_500);
  const t1 = await getPlayback();
  const delta = t1.time - t0.time;
  const ok = delta >= ADVANCE_MIN_S && t1.paused === false;
  recordCheck(
    "time_advances_while_playing",
    ok ? "pass" : "fail",
    ok
      ? `Time advanced by ${delta.toFixed(3)}s while playing`
      : `Time did not advance enough (delta=${delta.toFixed(3)}s, paused=${t1.paused})`,
    { t0, t1, delta, minRequired: ADVANCE_MIN_S },
  );
  if (!ok) throw new Error("Replay time did not advance while playing");
  return { t0, t1, delta };
}

async function provePause() {
  await logEvent("step", "Pause and verify time holds approximately steady");
  const before = await postPlayback({ paused: true });
  await delay(500);
  const t0 = await getPlayback();
  await delay(3_000);
  const t1 = await getPlayback();
  const drift = Math.abs(t1.time - t0.time);
  const ok = t1.paused === true && drift <= PAUSE_DRIFT_MAX_S;
  recordCheck(
    "pause_holds_time",
    ok ? "pass" : "fail",
    ok
      ? `Paused; drift=${drift.toFixed(3)}s`
      : `Pause failed (paused=${t1.paused}, drift=${drift.toFixed(3)}s)`,
    { before, t0, t1, drift, maxDrift: PAUSE_DRIFT_MAX_S },
  );
  if (!ok) throw new Error("Pause did not hold replay time");
  return { t0, t1, drift };
}

async function proveResume() {
  await logEvent("step", "Resume and verify time advances again");
  await postPlayback({ paused: false, speed: 1 });
  await delay(500);
  const t0 = await getPlayback();
  await delay(3_500);
  const t1 = await getPlayback();
  const delta = t1.time - t0.time;
  const ok = t1.paused === false && delta >= ADVANCE_MIN_S;
  recordCheck(
    "resume_advances_time",
    ok ? "pass" : "fail",
    ok
      ? `Resumed; advanced ${delta.toFixed(3)}s`
      : `Resume failed (paused=${t1.paused}, delta=${delta.toFixed(3)}s)`,
    { t0, t1, delta },
  );
  if (!ok) throw new Error("Resume did not advance replay time");
  return { t0, t1, delta };
}

async function proveSeek(targets) {
  await logEvent("step", "Seek to requested timestamps", { targets });
  /** @type {object[]} */
  const results = [];
  for (const target of targets) {
    await postPlayback({ paused: true, time: target });
    const settled = await waitUntilNotSeeking();
    await delay(400);
    const after = await getPlayback();
    const err = Math.abs(after.time - target);
    const ok = err <= SEEK_TOLERANCE_S;
    results.push({
      target,
      landed: after.time,
      errorAbs: err,
      ok,
      paused: after.paused,
      seeking: after.seeking,
      sample: after,
      settled,
    });
    await logEvent(ok ? "check" : "error", `seek ${target}s -> ${after.time}s (err=${err})`, {
      target,
      landed: after.time,
      errorAbs: err,
    });
  }
  const allOk = results.every((r) => r.ok);
  recordCheck(
    "seek_multiple_targets",
    allOk ? "pass" : "fail",
    allOk
      ? `All ${results.length} seeks within ±${SEEK_TOLERANCE_S}s`
      : `One or more seeks outside ±${SEEK_TOLERANCE_S}s`,
    { results, toleranceS: SEEK_TOLERANCE_S },
  );
  if (!allOk) throw new Error("Seek verification failed");
  return results;
}

async function writeReport(report) {
  await fsp.writeFile(REPORT_PATH, JSON.stringify(report, null, 2), "utf8");
  await logEvent("step", "Wrote probe_report.json", { path: REPORT_PATH });
}

async function main() {
  const startedAt = nowIso();
  await resetOutputs();
  await logEvent("start", "R.0 Replay Control Proof of Concept starting", {
    cwd: process.cwd(),
    node: process.version,
    platform: process.platform,
  });

  if (!fs.existsSync(RIOT_CA_PATH)) {
    throw new Error(`Missing Riot CA at ${RIOT_CA_PATH}`);
  }

  const roflPath = path.resolve(argValue("--rofl") || DEFAULT_ROFL);
  /** @type {Record<string, any>} */
  const report = {
    workOrder: "R.0",
    title: "Replay Control Proof of Concept",
    result: "FAILED",
    startedAt,
    finishedAt: null,
    roflPath,
    leagueInstall: null,
    launch: null,
    patchCompatibility: null,
    replayApi: null,
    capabilities: null,
    playbackProofs: {},
    checks: {},
    failures: [],
    implications: null,
    notes: [
      "Isolated spike under spikes/replay_probe/. Does not modify H.1–H.9 production behavior.",
      "TLS uses Riot Games CA (riotgames.pem) with hostname check disabled for 127.0.0.1 — not verify=false.",
      "Live Client Data during replay is informational and does not gate R.0 pass/fail.",
    ],
  };

  try {
    const header = await inspectRofl(roflPath);
    const install = await discoverLeagueInstall();
    report.leagueInstall = install;

    const roflVer = header.embeddedVersion;
    const clientVer = install.clientVersion;
    const patchFamily = (v) => (v ? String(v).match(/^(\d+\.\d+)/)?.[1] ?? null : null);
    const families = [
      patchFamily(roflVer),
      patchFamily(clientVer),
      patchFamily(install.cfgVersion),
    ].filter(Boolean);
    report.patchCompatibility = {
      roflEmbeddedVersion: roflVer,
      clientCodeVersion: clientVer,
      cfgVersion: install.cfgVersion,
      apparentlySamePatchFamily:
        families.length > 0 && families.every((f) => f === families[0]),
    };
    recordCheck(
      "patch_compatibility",
      report.patchCompatibility.apparentlySamePatchFamily ? "pass" : "info",
      `ROFL=${roflVer} client=${clientVer} cfg=${install.cfgVersion}`,
      report.patchCompatibility,
    );

    await ensureReplayApiEnabled(install);

    let launchInfo;
    try {
      launchInfo = await launchViaGameExe(install, roflPath);
    } catch (err) {
      await logEvent("error", `game_exe launch failed: ${err}`, { err: String(err) });
      launchInfo = await launchViaShellOpen(roflPath);
    }
    report.launch = launchInfo;
    recordCheck("replay_launch_attempted", "pass", `Launch method=${launchInfo.method}`, launchInfo);

    const proc = await waitForProcess("League of Legends", 90_000);
    if (proc) {
      recordCheck("replay_process_detected", "pass", `Process detected pid=${proc.pid}`, proc);
      await logEvent("check", "League of Legends process detected", proc);
    } else {
      recordCheck(
        "replay_process_detected",
        "info",
        "Could not confirm League of Legends process by name; continuing to API poll",
      );
    }

    const initialPlayback = await waitForReplayApi();
    report.replayApi = {
      baseUrl: REPLAY_BASE,
      initialPlayback,
      tls: {
        mode: "riot_ca_verify",
        caFile: "riotgames.pem",
        hostnameCheck: "disabled_for_loopback",
        insecureSkipVerify: false,
      },
    };
    recordCheck("playback_time_readable", "pass", "Playback time readable", initialPlayback);

    const capabilities = await inventoryCapabilities();
    report.capabilities = capabilities;

    report.playbackProofs.timeAdvances = await proveTimeAdvances();
    report.playbackProofs.pause = await provePause();
    report.playbackProofs.resume = await proveResume();

    const length = (await getPlayback()).length || 0;
    const seekTargets = [60, 180, 300]
      .map((t) => Math.min(t, Math.max(5, length - 5)))
      .filter((t, i, arr) => arr.indexOf(t) === i);
    if (length > 0 && seekTargets.length === 0) seekTargets.push(Math.min(30, length / 2));
    report.playbackProofs.seeks = await proveSeek(seekTargets.length ? seekTargets : [30, 60]);

    // Final essential gate: all critical checks passed.
    const critical = [
      "rofl_readable",
      "league_install",
      "replay_api_available",
      "playback_time_readable",
      "time_advances_while_playing",
      "pause_holds_time",
      "resume_advances_time",
      "seek_multiple_targets",
    ];
    const criticalFailed = critical.filter((id) => checks[id]?.status === "fail");
    if (criticalFailed.length === 0) {
      report.result = "PASSED";
      report.implications = {
        nativeRoflArchitecture: "viable_for_further_spikes",
        summary:
          "Real .rofl launched in the installed League client and was programmatically controlled via the local Replay API (read time, pause, resume, seek). A native .rofl-driven review path is worth pursuing in later R.* spikes; do not fold into H.1–H.9 yet.",
      };
    } else {
      report.result = "FAILED";
      report.implications = {
        nativeRoflArchitecture: "blocked_or_incomplete",
        summary: `Critical checks failed: ${criticalFailed.join(", ")}`,
      };
    }
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    await logEvent("error", `Probe aborted: ${message}`, {
      stack: err && err.stack ? String(err.stack) : null,
    });
    report.result = "FAILED";
    report.abortedWith = message;
    report.implications = {
      nativeRoflArchitecture: "not_proven",
      summary:
        "R.0 did not fully prove programmatic replay control on this machine. Do not begin production native-.rofl work until this spike passes.",
    };
  } finally {
    report.checks = checks;
    report.failures = failures;
    report.finishedAt = nowIso();
    await writeReport(report);
    await logEvent("end", `R.0 result=${report.result}`, {
      result: report.result,
      failures,
      reportPath: REPORT_PATH,
      sessionPath: SESSION_PATH,
    });
    console.log("\n=== R.0 RESULT:", report.result, "===");
    if (report.result !== "PASSED") process.exitCode = 1;
  }
}

main().catch(async (err) => {
  console.error(err);
  try {
    await logEvent("error", `Fatal: ${err}`);
  } catch {
    /* ignore */
  }
  process.exitCode = 1;
});
