const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
const ALARM = "ulsb-periodic-sync";
const PROBE_ALARM = "ulsb-probe-jobs";
let debounceTimer = null;
let probeBusy = false;

async function getState(defaults) {
  return await api.storage.local.get(defaults);
}

async function setState(values) {
  await api.storage.local.set(values);
}

function browserLabel() {
  const ua = navigator.userAgent || "";
  if (navigator.brave) return "Brave";
  if (/Firefox/i.test(ua)) return "Firefox";
  if (/Edg\//i.test(ua)) return "Edge";
  if (/OPR\//i.test(ua)) return "Opera";
  if (/Chrome\//i.test(ua)) return "Chrome";
  return "Chromium";
}

function siteEnabled(site) {
  return site.enabled !== false;
}

async function requestJson(method, path, body = null, authenticated = true) {
  const state = await getState({
    brokerUrl: DEFAULT_BROKER,
    clientToken: "",
    clientId: ""
  });
  const headers = {
    "X-ULSB-Extension-Origin": api.runtime.getURL("").replace(/\/$/, "")
  };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (authenticated) {
    if (!state.clientToken || !state.clientId) {
      throw new Error("Broker eşleştirmesi yok.");
    }
    headers.Authorization = `Bearer ${state.clientToken}`;
    headers["X-ULSB-Client-ID"] = state.clientId;
  }
  const options = {method, headers, cache: "no-store"};
  if (body !== null) options.body = JSON.stringify(body);
  const response = await fetch(`${state.brokerUrl}${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function postJson(path, body, authenticated = true) {
  return await requestJson("POST", path, body, authenticated);
}

async function pairBroker(payload) {
  const state = await getState({clientId: ""});
  const clientId = state.clientId || crypto.randomUUID();
  await setState({brokerUrl: payload.brokerUrl, clientId});
  const result = await postJson("/v1/pair", {
    code: payload.code,
    client_id: clientId,
    label: payload.label,
    browser: browserLabel()
  }, false);
  await setState({
    clientId,
    clientToken: result.client_token,
    profileLabel: payload.label,
    pairedAt: result.paired_at
  });
  return result;
}

async function sites() {
  const state = await getState({sites: []});
  return Array.isArray(state.sites) ? state.sites : [];
}

async function saveSites(value) {
  await setState({sites: value});
}

async function maybeKeepalive(site) {
  const minutes = Number(site.keepaliveMinutes || 0);
  if (!site.keepaliveUrl || minutes < 5) return;
  const previous = site.lastKeepaliveAt ? Date.parse(site.lastKeepaliveAt) : 0;
  if (Date.now() - previous < minutes * 60000) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(site.keepaliveUrl, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "follow",
      signal: controller.signal
    });
    site.lastKeepaliveStatus = response.status;
    site.lastKeepaliveAt = new Date().toISOString();
  } finally {
    clearTimeout(timeout);
  }
}

async function syncSite(site) {
  if (!siteEnabled(site)) {
    site.lastStatus = "DISABLED";
    site.lastError = "";
    return;
  }

  await maybeKeepalive(site);
  const details = {url: site.url};
  if (site.storeId) details.storeId = site.storeId;
  const cookies = await api.cookies.getAll(details);
  cookies.sort((a, b) => {
    const diff = (b.path || "/").length - (a.path || "/").length;
    return diff || String(a.name).localeCompare(String(b.name));
  });
  const state = await getState({clientId: "", profileLabel: ""});
  const currentBrowser = browserLabel();
  const result = await postJson("/v1/push", {
    client_id: state.clientId,
    name: site.name,
    title: String(site.title || "").slice(0, 300),
    url: site.url,
    browser: currentBrowser,
    store_id: site.storeId || "",
    keepalive_url: site.keepaliveUrl || "",
    keepalive_minutes: Number(site.keepaliveMinutes || 0),
    last_keepalive_status: site.lastKeepaliveStatus ?? null,
    cookies: cookies.map(cookie => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      httpOnly: cookie.httpOnly,
      sameSite: cookie.sameSite,
      expirationDate: cookie.expirationDate,
      storeId: cookie.storeId,
      partitionKey: cookie.partitionKey
    }))
  });
  site.enabled = true;
  site.browser = currentBrowser;
  site.profileLabel = state.profileLabel || "";
  site.lastStatus = "READY";
  site.lastSync = new Date().toISOString();
  site.cookieCount = result.cookie_count;
  site.lastError = "";
}

async function syncAll() {
  const current = await sites();
  for (const site of current) {
    if (!siteEnabled(site)) {
      site.lastStatus = "DISABLED";
      site.lastError = "";
      continue;
    }
    try {
      await syncSite(site);
    } catch (error) {
      site.lastStatus = "ERROR";
      site.lastError = String(error.message || error);
      site.lastSync = new Date().toISOString();
    }
  }
  await saveSites(current);
  return current;
}

async function syncOne(name) {
  const current = await sites();
  const site = current.find(item => item.name === name);
  if (!site) throw new Error("Kayıt bulunamadı.");
  if (!siteEnabled(site)) {
    site.lastStatus = "DISABLED";
    site.lastError = "";
    await saveSites(current);
    return site;
  }
  try {
    await syncSite(site);
  } catch (error) {
    site.lastStatus = "ERROR";
    site.lastError = String(error.message || error);
  }
  await saveSites(current);
  return site;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForTabComplete(tabId, timeoutMs = 45000) {
  const initial = await api.tabs.get(tabId).catch(() => null);
  if (initial?.status === "complete") return;
  await new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      api.tabs.onUpdated.removeListener(listener);
      reject(new Error("Tab load timeout"));
    }, timeoutMs);
    const listener = (updatedId, changeInfo) => {
      if (updatedId !== tabId || changeInfo.status !== "complete" || settled) return;
      settled = true;
      clearTimeout(timer);
      api.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    api.tabs.onUpdated.addListener(listener);
  });
}

async function navigateTab(tabId, url) {
  await api.tabs.update(tabId, {url, active: false});
  try { await waitForTabComplete(tabId); } catch {}
  await sleep(1200);
}

async function readPage(tabId, includeAnchors = false) {
  const result = await api.scripting.executeScript({
    target: {tabId},
    func: include => {
      const text = (document.documentElement?.innerText || "").slice(0, 250000);
      const anchors = include ? Array.from(document.querySelectorAll("a[href]"), a => ({
        href: a.href || "",
        text: String(a.innerText || a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 400)
      })).slice(0, 1200) : [];
      return {href: location.href, title: document.title, text, anchors};
    },
    args: [includeAnchors]
  });
  return result?.[0]?.result || {href: "", title: "", text: "", anchors: []};
}

function safeHttpUrl(raw) {
  try {
    const url = new URL(raw);
    return ["http:", "https:"].includes(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

function safeDiscoveryUrl(raw, accountId, projectId) {
  const url = safeHttpUrl(raw);
  if (!url || url.hostname !== "app.basecamp.com") return false;
  const path = url.pathname.toLowerCase();
  const blocked = ["/edit", "/new", "/delete", "/destroy", "/trash", "/archive", "/complete", "/toggle", "/subscribe", "/unsubscribe", "/download"];
  if (blocked.some(token => path.includes(token))) return false;
  if (!url.pathname.includes(`/${accountId}/`)) return false;
  return url.pathname.includes(String(projectId)) || /\/todos\/[^/]+/i.test(url.pathname);
}

function isTodoDetail(raw) {
  const url = safeHttpUrl(raw);
  return Boolean(url && /\/todos\/[^/]+/i.test(url.pathname));
}

async function executeProbe(job) {
  const tab = await api.tabs.create({url: "about:blank", active: false});
  try {
    await navigateTab(tab.id, job.url);
    const page = await readPage(tab.id, false);
    const markers = Array.isArray(job.markers) ? job.markers.map(String) : [];
    const matched = markers.filter(marker => page.text.includes(marker));
    return {
      ok: true,
      kind: "probe",
      requested_url: job.url,
      final_url: page.href,
      title: page.title,
      matched_markers: matched
    };
  } finally {
    await api.tabs.remove(tab.id).catch(() => {});
  }
}

async function executeTodoDiscovery(job) {
  const start = new URL(job.url);
  const parts = start.pathname.split("/").filter(Boolean);
  if (parts.length < 3) throw new Error("Project URL çözümlenemedi.");
  const accountId = parts[0];
  const projectId = parts[parts.length - 1];
  const preferred = String(job.preferred_marker || "");
  const queue = [job.url];
  const seen = new Set();
  const fallback = [];
  const tab = await api.tabs.create({url: "about:blank", active: false});
  try {
    while (queue.length && seen.size < 24) {
      const current = queue.shift();
      if (!safeDiscoveryUrl(current, accountId, projectId) || seen.has(current)) continue;
      seen.add(current);
      await navigateTab(tab.id, current);
      const page = await readPage(tab.id, true);
      const priority = [];
      const secondary = [];
      for (const anchor of page.anchors || []) {
        const href = String(anchor.href || "");
        const text = String(anchor.text || "").trim();
        if (!safeDiscoveryUrl(href, accountId, projectId)) continue;
        if (preferred && text.includes(preferred)) {
          return {ok: true, kind: "discover_todo", found_url: href, marker: preferred, source: "controlled-marker"};
        }
        if (isTodoDetail(href) && text.length >= 4 && text.length <= 300) fallback.push({href, text});
        if (/todo/i.test(href) || /to-?do/i.test(text)) priority.push(href);
        else secondary.push(href);
      }
      for (const href of [...priority, ...secondary.slice(0, 6)]) {
        if (!seen.has(href) && !queue.includes(href)) queue.push(href);
      }
    }
    const generic = new Set(["to-do", "to-dos", "todo", "todos", "view", "open"]);
    const used = new Set();
    for (const candidate of fallback.slice(0, 20)) {
      const key = `${candidate.href}|${candidate.text}`;
      if (used.has(key) || generic.has(candidate.text.toLowerCase())) continue;
      used.add(key);
      await navigateTab(tab.id, candidate.href);
      const page = await readPage(tab.id, false);
      if (page.text.includes(candidate.text)) {
        return {ok: true, kind: "discover_todo", found_url: candidate.href, marker: candidate.text, source: "first-existing-todo"};
      }
    }
    throw new Error(`To-do resource bulunamadı: ${preferred || "marker yok"}`);
  } finally {
    await api.tabs.remove(tab.id).catch(() => {});
  }
}

async function executeProbeJob(job) {
  if (job.kind === "discover_todo") return await executeTodoDiscovery(job);
  if (job.kind === "probe") return await executeProbe(job);
  throw new Error(`Desteklenmeyen probe kind: ${job.kind}`);
}

async function pollProbeJobs() {
  if (probeBusy) return;
  const state = await getState({pairedAt: "", clientId: "", clientToken: ""});
  if (!state.pairedAt || !state.clientId || !state.clientToken) return;
  probeBusy = true;
  let job = null;
  try {
    const response = await requestJson("GET", "/v1/probe-jobs/next", null, true);
    job = response.job;
    if (!job) return;
    let result;
    try {
      result = await executeProbeJob(job);
    } catch (error) {
      result = {ok: false, kind: job.kind, error: String(error.message || error)};
    }
    await postJson("/v1/probe-jobs/result", {job_id: job.job_id, result}, true);
  } catch (error) {
    if (job) {
      try {
        await postJson("/v1/probe-jobs/result", {
          job_id: job.job_id,
          result: {ok: false, kind: job.kind, error: String(error.message || error)}
        }, true);
      } catch {}
    }
  } finally {
    probeBusy = false;
  }
}

async function ensureAlarms() {
  await api.alarms.create(ALARM, {periodInMinutes: 1});
  await api.alarms.create(PROBE_ALARM, {periodInMinutes: 0.5});
}

api.runtime.onInstalled.addListener(async () => {
  await ensureAlarms();
  await pollProbeJobs();
});

api.runtime.onStartup.addListener(async () => {
  await ensureAlarms();
  await syncAll();
  await pollProbeJobs();
});

api.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === ALARM) await syncAll();
  if (alarm.name === PROBE_ALARM) await pollProbeJobs();
});

api.cookies.onChanged.addListener(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => syncAll(), 1200);
});

api.runtime.onMessage.addListener(message => {
  if (message?.type === "PAIR") return pairBroker(message.payload);
  if (message?.type === "SYNC_ALL") return syncAll();
  if (message?.type === "SYNC_ONE") return syncOne(message.name);
  if (message?.type === "POLL_PROBE_JOBS") return pollProbeJobs();
  return undefined;
});

setInterval(() => { void pollProbeJobs(); }, 5000);
void ensureAlarms();
void pollProbeJobs();
