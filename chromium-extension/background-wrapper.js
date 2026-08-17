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

const unwrappedExecuteProbeJob = executeProbeJob;
executeProbeJob = async function(job) {
  const cookieSnapshot = await captureProbeCookies();
  try {
    return await unwrappedExecuteProbeJob(job);
  } finally {
    await restoreProbeCookies(cookieSnapshot);
  }
};
