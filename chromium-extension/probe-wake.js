const wakeApi = globalThis.browser ?? globalThis.chrome;

function wakeProbeWorker() {
  try {
    const result = wakeApi.runtime.sendMessage({type: "POLL_PROBE_JOBS"});
    if (result && typeof result.catch === "function") result.catch(() => {});
  } catch {}
}

wakeProbeWorker();
setInterval(wakeProbeWorker, 2000);
