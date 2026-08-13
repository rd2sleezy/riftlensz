/**
 * Mac .rofl Replay API feasibility spike (throwaway).
 *
 * Does NOT modify production RiftLens code or game.cfg.
 * Does NOT enable macOS import in the product UI.
 *
 * Usage:
 *   node probe.mjs
 *   node probe.mjs --rofl "/path/to/NA1-5620410094.rofl"
 *   node probe.mjs --skip-launch   # only probe 2999 if already open
 *   node probe.mjs --launch-method open|direct|both
 */

import { spawn, execFile } from "node:child_process";
import fs from "node:fs";
import fsp from "node:fs/promises";
import https from "node:https";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SESSION_PATH = path.join(__dirname, "session.jsonl");
const REPORT_PATH = path.join(__dirname, "probe_report.json");
const RIOT_CA_PATH = path.join(__dirname, "riotgames.pem");

const DEFAULT_ROFL = path.join(
  os.homedir(),
  "Documents",
  "League of Legends",
  "Replays",
  "NA1-5620410094.rofl",
);

const APP_BUNDLE = "/Applications/League of Legends.app";
const LOL_ROOT = path.join(APP_BUNDLE, "Contents", "LoL");
/** On macOS, DATA/FINAL lives under Game/; GameBaseDir must point here (not LoL root). */
const GAME_DIR = path.join(LOL_ROOT, "Game");
const GAME_CFG = path.join(LOL_ROOT, "Config", "game.cfg");
const GAME_EXE = path.join(
  GAME_DIR,
  "LeagueofLegends.app",
  "Contents",
  "MacOS",
  "LeagueofLegends",
);

const REPLAY_HOST = "127.0.0.1";
const REPLAY_PORT = 2999;
const REPLAY_BASE = `https://${REPLAY_HOST}:${REPLAY_PORT}`;

const SEEK_TOLERANCE_S = 3.0;
const PAUSE_DRIFT_MAX_S = 1.0;
const ADVANCE_MIN_S = 1.0;
const API_WAIT_MS = 180_000;
const API_POLL_MS = 2_000;

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

function hasFlag(flag) {
  return process.argv.includes(flag);
}

async function logEvent(kind, message, data = undefined) {
  const entry = {
    ts: nowIso(),
    kind,
    message,
    ...(data !== undefined ? { data } : {}),
  };
  session.push(entry);
  await fsp.appendFile(SESSION_PATH, JSON.stringify(entry) + "\n", "utf8");
  const prefix = kind === "error" ? "!" : kind === "check" ? "*" : "-";
  console.log(`${prefix} [${kind}] ${message}`);
  if (data !== undefined) {
    const preview = JSON.stringify(data);
    if (preview.length < 800) console.log(`    ${preview}`);
  }
}

function recordCheck(id, status, detail, evidence = undefined) {
  checks[id] = { id, status, detail, ...(evidence !== undefined ? { evidence } : {}), ts: nowIso() };
  if (status === "fail") failures.push(`${id}: ${detail}`);
}

function createHttpsAgent() {
  const ca = fs.readFileSync(RIOT_CA_PATH, "utf8");
  // Pin Riot CA; hostname check off for loopback leaf (same as production tls.py).
  // This is NOT verify=false.
  return new https.Agent({
    ca,
    rejectUnauthorized: true,
    checkServerIdentity: () => undefined,
  });
}

function requestJson(method, apiPath, body = null, timeoutMs = 10_000) {
  const agent = createHttpsAgent();
  const payload = body === null ? null : JSON.stringify(body);
  const url = new URL(apiPath, REPLAY_BASE);
  /** @type {import('node:https').RequestOptions} */
  const opts = {
    protocol: url.protocol,
    hostname: url.hostname,
    port: url.port,
    path: url.pathname + url.search,
    method,
    agent,
    headers: {
      Accept: "application/json",
      ...(payload
        ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) }
        : {}),
    },
    timeout: timeoutMs,
  };
  return new Promise((resolve) => {
    const req = https.request(opts, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        let json = null;
        try {
          json = raw ? JSON.parse(raw) : null;
        } catch {
          json = null;
        }
        resolve({
          ok: (res.statusCode ?? 500) >= 200 && (res.statusCode ?? 500) < 300,
          status: res.statusCode ?? 0,
          raw,
          json,
        });
      });
    });
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, status: 0, raw: "", json: null, error: "timeout" });
    });
    req.on("error", (err) => {
      resolve({ ok: false, status: 0, raw: "", json: null, error: String(err) });
    });
    if (payload) req.write(payload);
    req.end();
  });
}

function portOpen(host, port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.on("connect", () => done(true));
    socket.on("timeout", () => done(false));
    socket.on("error", () => done(false));
  });
}

async function locateInstall() {
  await logEvent("step", "Locate League on macOS");
  const evidence = {
    appBundle: APP_BUNDLE,
    lolRoot: LOL_ROOT,
    gameDir: GAME_DIR,
    gameCfg: GAME_CFG,
    gameExe: GAME_EXE,
    appExists: fs.existsSync(APP_BUNDLE),
    gameCfgExists: fs.existsSync(GAME_CFG),
    gameExeExists: fs.existsSync(GAME_EXE),
    bootstrapWadExists: fs.existsSync(
      path.join(GAME_DIR, "DATA", "FINAL", "Bootstrap.macos.wad.client"),
    ),
  };
  if (!evidence.appExists || !evidence.gameExeExists) {
    recordCheck("locate_league", "fail", "League install incomplete", evidence);
    await logEvent("check", "locate_league FAIL", evidence);
    return null;
  }
  let enableReplayApi = null;
  let cfgText = "";
  if (evidence.gameCfgExists) {
    cfgText = await fsp.readFile(GAME_CFG, "utf8");
    const m = cfgText.match(/^\s*EnableReplayApi\s*=\s*(\d+)/im);
    enableReplayApi = m ? m[1] : null;
  }
  evidence.enableReplayApi = enableReplayApi;
  evidence.enableReplayApiPresent = enableReplayApi !== null;
  recordCheck(
    "locate_league",
    "pass",
    "Found League.app + Game client binary + game.cfg",
    evidence,
  );
  await logEvent("check", "locate_league PASS", evidence);
  if (enableReplayApi !== "1") {
    recordCheck(
      "enable_replay_api_cfg",
      "info",
      "EnableReplayApi is not set to 1 in game.cfg (spike will NOT edit config without approval)",
      { enableReplayApi, path: GAME_CFG },
    );
    await logEvent("check", "enable_replay_api_cfg INFO — not enabling without approval", {
      enableReplayApi,
    });
  } else {
    recordCheck("enable_replay_api_cfg", "pass", "EnableReplayApi=1 already present", {
      path: GAME_CFG,
    });
  }
  return evidence;
}

async function validateRofl(roflPath) {
  await logEvent("step", "Validate .rofl", { roflPath });
  const st = await fsp.stat(roflPath);
  if (!st.isFile() || st.size < 64) {
    recordCheck("rofl_readable", "fail", "Missing or too small", { roflPath, size: st.size });
    throw new Error("rofl invalid");
  }
  const fd = await fsp.open(roflPath, "r");
  const buf = Buffer.alloc(64);
  await fd.read(buf, 0, 64, 0);
  await fd.close();
  const magic = buf.slice(0, 4).toString("ascii");
  const base = path.basename(roflPath);
  const idMatch = base.match(/^([A-Za-z0-9]+)-(\d+)\.rofl$/i);
  const evidence = {
    roflPath,
    size: st.size,
    magic,
    basename: base,
    platformId: idMatch?.[1] ?? null,
    gameId: idMatch?.[2] ?? null,
  };
  const ok = magic === "RIOT" && idMatch !== null;
  recordCheck(
    "rofl_readable",
    ok ? "pass" : "fail",
    ok ? "ROFL present, RIOT magic, filename identity parsed" : "ROFL validation failed",
    evidence,
  );
  await logEvent("check", `rofl_readable ${ok ? "PASS" : "FAIL"}`, evidence);
  if (!ok) throw new Error("rofl validation failed");
  return evidence;
}

async function launchViaOpen(roflPath) {
  await logEvent("step", "Launch via macOS `open` (file association)");
  await new Promise((resolve, reject) => {
    execFile("open", [roflPath], (err) => (err ? reject(err) : resolve()));
  });
  return { method: "open", roflPath };
}

async function launchViaDirect(roflPath, install) {
  // Wrong GameBaseDir (LoL root) causes ALE-18967991 / missing Bootstrap.macos.wad.client.
  const gameBaseDir = install.gameDir || GAME_DIR;
  const args = [
    roflPath,
    `-GameBaseDir=${gameBaseDir}`,
    "-Region=NA",
    "-PlatformID=NA1",
    "-Locale=en_US",
    "-SkipBuild",
  ];
  await logEvent("step", "Launch via LeagueofLegends binary (Mac GameBaseDir=Game)", {
    exe: install.gameExe,
    cwd: gameBaseDir,
    args,
  });
  // Remove accidental SOFT_REPAIR from prior wrong-GameBaseDir crashes (probe-created).
  const softRepair = path.join(GAME_DIR, "LeagueofLegends.app", "Contents", "SOFT_REPAIR");
  try {
    if (fs.existsSync(softRepair)) {
      fs.unlinkSync(softRepair);
      await logEvent("step", "Removed accidental SOFT_REPAIR from prior failed probes");
    }
  } catch (err) {
    await logEvent("error", `Could not remove SOFT_REPAIR: ${err}`);
  }
  const child = spawn(install.gameExe, args, {
    cwd: gameBaseDir,
    detached: true,
    stdio: "ignore",
  });
  child.unref();
  return {
    method: "direct_exe_gamebasedir_game",
    pid: child.pid ?? null,
    exe: install.gameExe,
    gameBaseDir,
    args,
  };
}

async function listLeagueishProcesses() {
  return new Promise((resolve) => {
    execFile("pgrep", ["-fl", "League|Riot"], (err, stdout) => {
      if (err) return resolve([]);
      resolve(
        stdout
          .toString()
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean),
      );
    });
  });
}

async function waitForPort(timeoutMs = API_WAIT_MS) {
  await logEvent("step", `Wait for TCP ${REPLAY_HOST}:${REPLAY_PORT}`, { timeoutMs });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await portOpen(REPLAY_HOST, REPLAY_PORT)) {
      recordCheck("port_2999", "pass", "Port 2999 accepting TCP connections");
      await logEvent("check", "port_2999 PASS");
      return true;
    }
    await delay(API_POLL_MS);
  }
  recordCheck("port_2999", "fail", `Port 2999 not open within ${timeoutMs}ms`);
  await logEvent("check", "port_2999 FAIL");
  return false;
}

async function probeOpenApiAndPlayback() {
  await logEvent("step", "Probe OpenAPI + /replay/playback");
  const openapi = await requestJson("GET", "/swagger/v3/openapi.json", null, 15_000);
  const paths = openapi.json?.paths ? Object.keys(openapi.json.paths) : [];
  const hasPlayback = paths.includes("/replay/playback") || paths.some((p) => p.includes("playback"));
  recordCheck(
    "openapi_playback",
    openapi.ok && hasPlayback ? "pass" : openapi.ok ? "fail" : "fail",
    openapi.ok
      ? hasPlayback
        ? "OpenAPI reachable; /replay/playback documented"
        : "OpenAPI reachable but /replay/playback not listed"
      : `OpenAPI failed: ${openapi.error || openapi.status}`,
    {
      status: openapi.status,
      error: openapi.error ?? null,
      title: openapi.json?.info?.title ?? null,
      pathCount: paths.length,
      hasPlayback,
      samplePaths: paths.slice(0, 30),
    },
  );
  await logEvent("check", "openapi_playback", checks.openapi_playback);

  const playback = await requestJson("GET", "/replay/playback");
  const length = Number(playback.json?.length ?? 0);
  const time = Number(playback.json?.time ?? NaN);
  const paused = playback.json?.paused;
  const ok =
    playback.ok && Number.isFinite(length) && length > 0 && Number.isFinite(time);
  recordCheck(
    "playback_get",
    ok ? "pass" : "fail",
    ok
      ? `GET /replay/playback length=${length} time=${time} paused=${paused}`
      : `GET /replay/playback failed status=${playback.status} err=${playback.error ?? ""}`,
    { status: playback.status, json: playback.json, error: playback.error ?? null },
  );
  await logEvent("check", "playback_get", checks.playback_get);
  return { openapi, playback, length, time, paused, ok };
}

async function sleep(ms) {
  await delay(ms);
}

async function controlTests(length) {
  await logEvent("step", "Real playback control: pause / play / seek");

  // Pause
  let res = await requestJson("POST", "/replay/playback", { paused: true });
  await sleep(1500);
  let got = await requestJson("GET", "/replay/playback");
  const t1 = Number(got.json?.time ?? NaN);
  await sleep(1500);
  got = await requestJson("GET", "/replay/playback");
  const t2 = Number(got.json?.time ?? NaN);
  const pauseOk =
    res.ok &&
    got.ok &&
    got.json?.paused === true &&
    Number.isFinite(t1) &&
    Number.isFinite(t2) &&
    Math.abs(t2 - t1) <= PAUSE_DRIFT_MAX_S;
  recordCheck(
    "pause",
    pauseOk ? "pass" : "fail",
    pauseOk ? `Paused; drift=${Math.abs(t2 - t1).toFixed(3)}s` : "Pause did not hold clock",
    { post: res.json ?? res.error, t1, t2, get: got.json },
  );

  // Play
  res = await requestJson("POST", "/replay/playback", { paused: false, seeking: false });
  await sleep(2500);
  got = await requestJson("GET", "/replay/playback");
  const tPlay0 = Number(got.json?.time ?? NaN);
  await sleep(2500);
  got = await requestJson("GET", "/replay/playback");
  const tPlay1 = Number(got.json?.time ?? NaN);
  const playOk =
    res.ok &&
    got.ok &&
    got.json?.paused === false &&
    Number.isFinite(tPlay0) &&
    Number.isFinite(tPlay1) &&
    tPlay1 - tPlay0 >= ADVANCE_MIN_S;
  recordCheck(
    "play",
    playOk ? "pass" : "fail",
    playOk ? `Playing; advanced ${(tPlay1 - tPlay0).toFixed(2)}s` : "Play did not advance time",
    { post: res.json ?? res.error, tPlay0, tPlay1, get: got.json },
  );

  // Seeks
  const targets = [
    Math.min(30, Math.max(5, length * 0.05)),
    Math.min(length * 0.5, length - 10),
    Math.min(length * 0.8, length - 5),
  ].map((t) => Math.max(0, Math.min(length - 1, t)));

  const seekResults = [];
  for (const target of targets) {
    await requestJson("POST", "/replay/playback", { paused: true });
    res = await requestJson("POST", "/replay/playback", {
      time: target,
      paused: true,
      seeking: true,
    });
    await sleep(2000);
    got = await requestJson("GET", "/replay/playback");
    const landed = Number(got.json?.time ?? NaN);
    const ok =
      res.ok &&
      got.ok &&
      Number.isFinite(landed) &&
      Math.abs(landed - target) <= SEEK_TOLERANCE_S;
    seekResults.push({ target, landed, ok, get: got.json, postOk: res.ok });
    await logEvent("check", `seek target=${target} landed=${landed} ok=${ok}`, {
      target,
      landed,
    });
  }
  const seekOk = seekResults.every((r) => r.ok);
  recordCheck(
    "seek",
    seekOk ? "pass" : "fail",
    seekOk ? "All seeks landed within tolerance" : "One or more seeks failed",
    { seekResults, toleranceS: SEEK_TOLERANCE_S },
  );
  return { pauseOk, playOk, seekOk };
}

async function probeOptional() {
  await logEvent("step", "Optional endpoint discovery");
  const endpoints = [
    "/replay/game",
    "/replay/render",
    "/replay/recording",
    "/liveclientdata/gamestats",
    "/liveclientdata/eventdata",
  ];
  /** @type {Record<string, any>} */
  const out = {};
  for (const ep of endpoints) {
    const res = await requestJson("GET", ep);
    out[ep] = {
      ok: res.ok,
      status: res.status,
      error: res.error ?? null,
      sample:
        res.json && typeof res.json === "object"
          ? Object.keys(res.json).slice(0, 12)
          : null,
    };
  }
  recordCheck("optional_endpoints", "info", "Discovery only", out);
  await logEvent("check", "optional_endpoints", out);
  return out;
}

function decideVerdict() {
  const pass = (id) => checks[id]?.status === "pass";
  if (pass("playback_get") && pass("pause") && pass("play") && pass("seek")) {
    return "MAC_REPLAY_SUPPORTED";
  }
  if (pass("port_2999") || pass("openapi_playback") || pass("playback_get")) {
    return "MAC_REPLAY_PARTIAL";
  }
  if (checks.replay_visibly_launched?.status === "pass" && !pass("port_2999")) {
    return "MAC_REPLAY_PARTIAL";
  }
  if (checks.locate_league?.status === "fail" || checks.rofl_readable?.status === "fail") {
    return "INCONCLUSIVE";
  }
  if (checks.launch_attempted?.status === "pass" && !pass("port_2999")) {
    // Could be EnableReplayApi missing — still a real negative for control path
    return "MAC_REPLAY_UNSUPPORTED";
  }
  return "INCONCLUSIVE";
}

async function main() {
  await fsp.writeFile(SESSION_PATH, "", "utf8");
  const roflPath = path.resolve(argValue("--rofl") || DEFAULT_ROFL);
  const skipLaunch = hasFlag("--skip-launch");
  const launchMethod = argValue("--launch-method") || "both";

  /** @type {Record<string, any>} */
  const report = {
    platform: process.platform,
    startedAt: nowIso(),
    roflPath,
    skipLaunch,
    launchMethod,
    checks: {},
    verdict: null,
    failures: [],
  };

  try {
    if (process.platform !== "darwin") {
      recordCheck("platform", "fail", `Not macOS (${process.platform})`);
      throw new Error("macOS only");
    }
    recordCheck("platform", "pass", "darwin");

    const install = await locateInstall();
    if (!install) throw new Error("install missing");

    await validateRofl(roflPath);

    let launchedVisibly = false;
    if (!skipLaunch) {
      try {
        if (launchMethod === "open" || launchMethod === "both") {
          const info = await launchViaOpen(roflPath);
          report.launchOpen = info;
          recordCheck("launch_attempted", "pass", "open invoked", info);
        }
      } catch (err) {
        await logEvent("error", `open launch failed: ${err}`);
        recordCheck("launch_open", "fail", String(err));
      }
      try {
        if (launchMethod === "direct" || launchMethod === "both") {
          // Prefer open first; direct is secondary experiment after a short wait
          if (launchMethod === "direct") {
            const info = await launchViaDirect(roflPath, install);
            report.launchDirect = info;
            recordCheck("launch_attempted", "pass", "direct exe invoked", info);
          } else {
            await sleep(8_000);
            const procs = await listLeagueishProcesses();
            const gameRunning = procs.some((p) => /LeagueofLegends|LeagueClient/i.test(p));
            if (!gameRunning && !(await portOpen(REPLAY_HOST, REPLAY_PORT))) {
              await logEvent("step", "open did not bring up game/API; trying direct exe");
              const info = await launchViaDirect(roflPath, install);
              report.launchDirect = info;
            } else {
              await logEvent("step", "Skipping direct exe — League-ish process or port already up", {
                procs: procs.slice(0, 10),
              });
            }
          }
        }
      } catch (err) {
        await logEvent("error", `direct launch failed: ${err}`);
        recordCheck("launch_direct", "fail", String(err));
      }

      // Heuristic: League processes after launch
      await sleep(5_000);
      const procs = await listLeagueishProcesses();
      launchedVisibly = procs.some((p) => /LeagueofLegends|LeagueClient/i.test(p));
      recordCheck(
        "replay_visibly_launched",
        launchedVisibly ? "pass" : "fail",
        launchedVisibly
          ? "League-related processes observed after launch"
          : "No LeagueofLegends/LeagueClient process observed",
        { procs: procs.slice(0, 20) },
      );
      await logEvent("check", "replay_visibly_launched", checks.replay_visibly_launched);
    } else {
      recordCheck("launch_attempted", "skip", "--skip-launch");
    }

    const portOk = await waitForPort(skipLaunch ? 15_000 : API_WAIT_MS);
    if (!portOk) {
      report.verdict = decideVerdict();
      report.checks = checks;
      report.failures = failures;
      report.finishedAt = nowIso();
      await fsp.writeFile(REPORT_PATH, JSON.stringify(report, null, 2));
      await logEvent("error", "Aborting control tests — port 2999 never came up", {
        hint: "EnableReplayApi may be unset; spike did not edit game.cfg",
      });
      console.log(`\nVERDICT: ${report.verdict}`);
      return;
    }

    const playbackProbe = await probeOpenApiAndPlayback();
    if (!playbackProbe.ok) {
      report.verdict = decideVerdict();
      report.checks = checks;
      report.failures = failures;
      report.finishedAt = nowIso();
      await fsp.writeFile(REPORT_PATH, JSON.stringify(report, null, 2));
      console.log(`\nVERDICT: ${report.verdict}`);
      return;
    }

    await controlTests(playbackProbe.length);
    await probeOptional();

    report.verdict = decideVerdict();
    report.checks = checks;
    report.failures = failures;
    report.finishedAt = nowIso();
    await fsp.writeFile(REPORT_PATH, JSON.stringify(report, null, 2));
    console.log(`\nVERDICT: ${report.verdict}`);
    if (failures.length) {
      console.log("Failures:");
      for (const f of failures) console.log(`  - ${f}`);
    }
  } catch (err) {
    await logEvent("error", String(err));
    report.verdict = decideVerdict();
    report.checks = checks;
    report.failures = failures;
    report.error = String(err);
    report.finishedAt = nowIso();
    await fsp.writeFile(REPORT_PATH, JSON.stringify(report, null, 2));
    console.log(`\nVERDICT: ${report.verdict}`);
    process.exitCode = 1;
  }
}

await main();
