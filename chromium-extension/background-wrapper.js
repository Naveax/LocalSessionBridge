importScripts("background.js");

const probeCookieUrls = [
  "https://app.basecamp.com/",
  "https://launchpad.37signals.com/"
];

function probeCookieKey(cookie) {
  const partition = cookie.partitionKey ? JSON.stringify(cookie.partitionKey) : "";
  return [cookie.storeId || "", partition, cookie.name || "", cookie.domain || "", cookie.path || "/"].join("|");
}

function probeCookieUrl(cookie) {
  const host = String(cookie.domain || "").replace(/^\./, "");
  const scheme = cookie.secure ? "https" : "http";
  const path = String(cookie.path || "/");
  return `${scheme}://${host}${path.startsWith("/") ? path : `/${path}`}`;
}

async function captureProbeCookies() {
  const map = new Map();
  for (const url of probeCookieUrls) {
    const cookies = await api.cookies.getAll({url});
    for (const cookie of cookies) map.set(probeCookieKey(cookie), cookie);
  }
  return Array.from(map.values());
}

async function removeProbeCookie(cookie) {
  const details = {
    url: probeCookieUrl(cookie),
    name: cookie.name
  };
  if (cookie.storeId) details.storeId = cookie.storeId;
  if (cookie.partitionKey) details.partitionKey = cookie.partitionKey;
  await api.cookies.remove(details).catch(() => null);
}

async function setProbeCookie(cookie) {
  const details = {
    url: probeCookieUrl(cookie),
    name: cookie.name,
    value: cookie.value,
    path: cookie.path || "/",
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly)
  };
  if (!cookie.hostOnly && cookie.domain) details.domain = cookie.domain;
  if (cookie.sameSite && ["no_restriction", "lax", "strict", "unspecified"].includes(cookie.sameSite)) {
    details.sameSite = cookie.sameSite;
  }
  if (Number.isFinite(cookie.expirationDate)) details.expirationDate = cookie.expirationDate;
  if (cookie.storeId) details.storeId = cookie.storeId;
  if (cookie.partitionKey) details.partitionKey = cookie.partitionKey;
  await api.cookies.set(details);
}

async function restoreProbeCookies(snapshot) {
  const before = new Map(snapshot.map(cookie => [probeCookieKey(cookie), cookie]));
  const current = await captureProbeCookies();
  for (const cookie of current) {
    if (!before.has(probeCookieKey(cookie))) await removeProbeCookie(cookie);
  }
  for (const cookie of snapshot) await setProbeCookie(cookie);
}

executeTodoDiscovery = async function(job) {
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
    while (queue.length && seen.size < 32) {
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
          if (isTodoDetail(href)) {
            return {
              ok: true,
              kind: "discover_todo",
              found_url: href,
              marker: preferred,
              source: "controlled-marker-strict-detail"
            };
          }

          if (!seen.has(href) && !queue.includes(href)) {
            priority.unshift(href);
          }
          continue;
        }

        if (isTodoDetail(href) && text.length >= 4 && text.length <= 300) {
          fallback.push({href, text});
        }

        if (/todo/i.test(href) || /to-?do/i.test(text)) priority.push(href);
        else secondary.push(href);
      }

      for (const href of [...priority, ...secondary.slice(0, 6)]) {
        if (!seen.has(href) && !queue.includes(href)) queue.push(href);
      }
    }

    const generic = new Set(["to-do", "to-dos", "todo", "todos", "view", "open"]);
    const used = new Set();

    for (const candidate of fallback.slice(0, 30)) {
      const key = `${candidate.href}|${candidate.text}`;
      if (used.has(key) || generic.has(candidate.text.toLowerCase())) continue;
      used.add(key);

      await navigateTab(tab.id, candidate.href);
      const page = await readPage(tab.id, false);

      if (preferred && page.text.includes(preferred)) {
        return {
          ok: true,
          kind: "discover_todo",
          found_url: candidate.href,
          marker: preferred,
          source: "controlled-marker-detail-probe"
        };
      }

      if (!preferred && page.text.includes(candidate.text)) {
        return {
          ok: true,
          kind: "discover_todo",
          found_url: candidate.href,
          marker: candidate.text,
          source: "first-existing-todo-detail"
        };
      }
    }

    throw new Error(`Tekil To-do detail resource bulunamadı: ${preferred || "marker yok"}`);
  } finally {
    await api.tabs.remove(tab.id).catch(() => {});
  }
};

const unwrappedExecuteProbeJob = executeProbeJob;
executeProbeJob = async function(job) {
  const cookieSnapshot = await captureProbeCookies();
  try {
    return await unwrappedExecuteProbeJob(job);
  } finally {
    await restoreProbeCookies(cookieSnapshot);
  }
};
